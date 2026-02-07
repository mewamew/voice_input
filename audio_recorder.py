"""
录音模块 - 支持开始/停止控制的流式录音
"""
import threading
from typing import Optional
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
import io
import base64


# 录音参数
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1  # 单声道


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

    def set_device(self, device_id: Optional[int]):
        """设置录音设备"""
        with self._lock:
            self.device_id = device_id

    def start(self):
        """开始录音"""
        with self._lock:
            if self._recording:
                return

            self._audio_chunks = []
            self._recording = True

            # 创建输入流
            self._stream = sd.InputStream(
                device=self.device_id,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.int16,
                callback=self._audio_callback
            )
            self._stream.start()

    def stop(self) -> np.ndarray:
        """
        停止录音并返回录制的音频数据

        Returns:
            录制的音频数据 (numpy array)
        """
        with self._lock:
            if not self._recording:
                return np.array([], dtype=np.int16)

            self._recording = False

            if self._stream:
                self._stream.stop()
                self._stream.close()
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
        if self._recording:
            self._audio_chunks.append(indata.copy())


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
