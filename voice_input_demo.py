"""
语音输入 Demo - 使用麦克风录音并调用阿里云 ASR 模型进行语音识别
"""
import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np
import base64
import io
import os
from openai import OpenAI

# 录音参数
SAMPLE_RATE = 16000  # 采样率
CHANNELS = 1  # 单声道


def record_audio(duration: float = 5.0) -> np.ndarray:
    """
    录制音频

    Args:
        duration: 录音时长（秒）

    Returns:
        录制的音频数据
    """
    print(f"🎤 开始录音，请说话... ({duration}秒)")
    audio_data = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=np.int16
    )
    sd.wait()  # 等待录音完成
    print("✅ 录音完成！")
    return audio_data


def audio_to_base64(audio_data: np.ndarray, sample_rate: int) -> str:
    """
    将音频数据转换为 base64 编码的 WAV 格式

    Args:
        audio_data: 音频数据
        sample_rate: 采样率

    Returns:
        base64 编码的音频字符串
    """
    # 将音频数据写入内存中的 WAV 文件
    buffer = io.BytesIO()
    wav.write(buffer, sample_rate, audio_data)
    buffer.seek(0)

    # 转换为 base64
    audio_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    return audio_base64


def recognize_speech(audio_base64: str) -> str:
    """
    调用阿里云 ASR 模型进行语音识别

    Args:
        audio_base64: base64 编码的音频数据

    Returns:
        识别出的文字
    """
    # 从环境变量获取 API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # 调用 ASR 模型
    completion = client.chat.completions.create(
        model="qwen3-asr-flash",
        messages=[{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {
                    "data": f"data:audio/wav;base64,{audio_base64}"
                }
            }]
        }],
        stream=False,
        extra_body={"asr_options": {"enable_itn": False}}
    )

    return completion.choices[0].message.content


def main():
    """主函数"""
    print("=" * 50)
    print("语音输入 Demo - 阿里云 ASR")
    print("=" * 50)

    while True:
        # 提示用户输入录音时长
        try:
            duration_input = input("\n请输入录音时长（秒，默认5秒，输入 q 退出）: ").strip()

            if duration_input.lower() == 'q':
                print("再见！")
                break

            duration = float(duration_input) if duration_input else 5.0

            # 录音
            audio_data = record_audio(duration)

            # 转换为 base64
            print("🔄 正在处理音频...")
            audio_base64 = audio_to_base64(audio_data, SAMPLE_RATE)

            # 语音识别
            print("🔄 正在识别语音...")
            text = recognize_speech(audio_base64)

            # 输出结果
            print("\n" + "=" * 50)
            print("📝 识别结果:")
            print(text)
            print("=" * 50)

        except KeyboardInterrupt:
            print("\n\n已中断，再见！")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")


if __name__ == "__main__":
    main()
