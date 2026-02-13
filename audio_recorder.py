"""
录音模块 - 支持开始/停止控制的流式录音
"""
import threading
import time
from typing import Optional, Callable
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
import io
import base64
import webrtcvad


# 录音参数
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1  # 单声道
VAD_FRAME_MS = 30  # VAD 帧长度（毫秒），可选 10, 20, 30
VAD_FRAME_SAMPLES = int(SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 480 samples for 30ms


class AudioRecorder:
    """支持开始/停止控制的录音器"""

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS,
                 device_id: Optional[int] = None):
        """
        Args:
            sample_rate: 采样率
            channels: 声道数
            device_id: 麦克风设备 ID，None 表示使用系统默认设备
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.device_id = device_id

        self._recording = False
        self._audio_chunks = []
        self._stream = None
        self._lock = threading.Lock()

        # VAD 相关
        self._vad = webrtcvad.Vad(3)  # 敏感度 0-3，3 最敏感
        self._vad_buffer = np.array([], dtype=np.int16)  # 用于累积音频数据

        # 音频流回调（用于流式识别）
        self._on_audio_chunk: Optional[Callable[[bytes], None]] = None

        # 自动停止相关属性
        self._start_time: float = 0
        self._last_voice_time: float = 0
        self._max_duration: int = 60
        self._silence_timeout: int = 3
        self._auto_stop_callback: Optional[Callable[[str], None]] = None
        self._auto_stop_reason: Optional[str] = None
        self._auto_stopped: bool = False

    def set_device(self, device_id: Optional[int]):
        """设置录音设备"""
        with self._lock:
            self.device_id = device_id

    def start(self, max_duration: int = 60, silence_timeout: int = 3,
               on_auto_stop: Optional[Callable[[str], None]] = None,
               on_audio_chunk: Optional[Callable[[bytes], None]] = None):
        """开始录音

        Args:
            max_duration: 最长录音时长（秒）
            silence_timeout: 静音超时时间（秒）
            on_auto_stop: 自动停止时的回调函数，参数为停止原因 ('timeout' / 'silence')
            on_audio_chunk: 音频数据回调（PCM int16 bytes），用于流式识别
        """
        with self._lock:
            if self._recording:
                return

            self._audio_chunks = []
            self._vad_buffer = np.array([], dtype=np.int16)
            self._recording = True

            # 初始化自动停止相关属性
            self._start_time = time.time()
            self._last_voice_time = time.time()
            self._max_duration = max_duration
            self._silence_timeout = silence_timeout
            self._auto_stop_callback = on_auto_stop
            self._on_audio_chunk = on_audio_chunk
            self._auto_stop_reason = None
            self._auto_stopped = False

            try:
                # 创建输入流
                self._stream = sd.InputStream(
                    device=self.device_id,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=np.int16,
                    callback=self._audio_callback
                )
                self._stream.start()
            except Exception:
                # 启动失败时回滚状态，避免出现“显示录音中但实际未录音”
                if self._stream:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                self._stream = None
                self._recording = False
                self._audio_chunks = []
                self._vad_buffer = np.array([], dtype=np.int16)
                self._auto_stop_callback = None
                self._on_audio_chunk = None
                self._auto_stop_reason = None
                self._auto_stopped = False
                self._start_time = 0
                self._last_voice_time = 0
                raise

    def stop(self) -> np.ndarray:
        """
        停止录音并返回录制的音频数据

        Returns:
            录制的音频数据 (numpy array)
        """
        with self._lock:
            if not self._recording:
                return np.array([], dtype=np.int16)

            # 先设置标志，阻止 _audio_callback 触发自动停止
            self._recording = False
            self._auto_stopped = True

            if self._stream:
                try:
                    self._stream.stop()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            # 合并所有音频块
            if self._audio_chunks:
                audio_data = np.concatenate(self._audio_chunks)
            else:
                audio_data = np.array([], dtype=np.int16)

            self._audio_chunks = []
            return audio_data

    def is_recording(self) -> bool:
        """检查是否正在录音"""
        return self._recording

    def _audio_callback(self, indata, frames, time_info, status):
        """音频流回调函数"""
        if not self._recording or self._auto_stopped:
            return

        # 保存音频数据
        self._audio_chunks.append(indata.copy())

        # 流式回调：转发 PCM 数据
        if self._on_audio_chunk:
            try:
                self._on_audio_chunk(indata.flatten().tobytes())
            except Exception:
                pass

        # 将新数据添加到 VAD 缓冲区
        chunk = indata.flatten()
        self._vad_buffer = np.concatenate([self._vad_buffer, chunk])

        current_time = time.time()

        # 按帧处理 VAD 检测
        while len(self._vad_buffer) >= VAD_FRAME_SAMPLES:
            frame = self._vad_buffer[:VAD_FRAME_SAMPLES]
            self._vad_buffer = self._vad_buffer[VAD_FRAME_SAMPLES:]

            # 转换为 bytes 进行 VAD 检测
            frame_bytes = frame.tobytes()
            try:
                if self._vad.is_speech(frame_bytes, self.sample_rate):
                    self._last_voice_time = current_time
            except Exception:
                # VAD 检测失败时忽略
                pass

        # 检查是否超过最大时长
        if current_time - self._start_time >= self._max_duration:
            self._trigger_auto_stop('timeout')
            return

        # 检查静音是否超时
        if current_time - self._last_voice_time >= self._silence_timeout:
            self._trigger_auto_stop('silence')
            return

    def _trigger_auto_stop(self, reason: str):
        """触发自动停止"""
        # 双重检查：如果已经停止或不在录音状态，直接返回
        if self._auto_stopped or not self._recording:
            return

        self._auto_stopped = True
        self._auto_stop_reason = reason

        # 在新线程中调用回调，避免阻塞音频回调
        if self._auto_stop_callback:
            threading.Thread(target=self._auto_stop_callback, args=(reason,), daemon=True).start()

    def get_recording_duration(self) -> float:
        """获取当前录音时长（秒）"""
        if not self._recording:
            return 0
        return time.time() - self._start_time

    def get_auto_stop_reason(self) -> Optional[str]:
        """获取自动停止原因"""
        return self._auto_stop_reason


def audio_to_base64(audio_data: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """
    将音频数据转换为 base64 编码的 WAV 格式

    Args:
        audio_data: 音频数据
        sample_rate: 采样率

    Returns:
        base64 编码的音频字符串
    """
    if len(audio_data) == 0:
        return ""

    # 确保是一维数组
    if audio_data.ndim > 1:
        audio_data = audio_data.flatten()

    # 将音频数据写入内存中的 WAV 文件
    buffer = io.BytesIO()
    wav.write(buffer, sample_rate, audio_data)
    buffer.seek(0)

    # 转换为 base64
    audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    return audio_base64


if __name__ == "__main__":
    import time

    print("测试录音模块...")
    recorder = AudioRecorder()

    print("开始录音，3秒后停止...")
    recorder.start()
    time.sleep(3)
    audio_data = recorder.stop()

    print(f"录音完成！采样点数: {len(audio_data)}")
    print(f"时长: {len(audio_data) / SAMPLE_RATE:.2f} 秒")

    # 测试转 base64
    b64 = audio_to_base64(audio_data)
    print(f"Base64 长度: {len(b64)} 字符")
