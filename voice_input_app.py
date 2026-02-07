"""
语音输入法 - macOS 状态栏应用

使用可配置的快捷键触发录音，自动识别并输入文字
"""
import os
import threading
import webbrowser

# 隐藏 Dock 图标（必须在导入 rumps 之前设置）
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

import rumps
from enum import Enum
from openai import OpenAI

from keyboard_listener import KeyboardListener
from audio_recorder import AudioRecorder, audio_to_base64
from text_inputter import input_text
from config_manager import get_config, get_history_manager

# 设置服务端口
SETTINGS_PORT = 18321


class AppState(Enum):
    """应用状态"""
    IDLE = "idle"           # 空闲
    RECORDING = "recording" # 录音中
    PROCESSING = "processing"  # 识别处理中


class VoiceInputApp(rumps.App):
    """语音输入状态栏应用"""

    def __init__(self):
        # 获取脚本所在目录
        self.app_dir = os.path.dirname(os.path.abspath(__file__))

        # 图标路径
        self.icon_idle = os.path.join(self.app_dir, "microphone.slash.png")
        self.icon_recording = os.path.join(self.app_dir, "microphone.png")

        # 初始化应用
        super().__init__(
            name="语音输入",
            icon=self.icon_idle,
            template=True,  # 使用模板图标，自动适应深色/浅色模式
            quit_button="退出"
        )

        # 配置
        self.config = get_config()
        self._config_mtime = 0  # 配置文件修改时间

        # 运行标志
        self._running = True

        # 启动设置服务
        self._start_settings_server()

        # 启动配置监控
        self._start_config_watcher()

        # 状态
        self.state = AppState.IDLE
        self._state_lock = threading.Lock()

        # 录音器
        self.recorder = AudioRecorder(device_id=self.config.microphone_device_id)

        # 键盘监听器
        self.keyboard_listener = KeyboardListener(
            callback=self._on_shortcut,
            shortcut_key=self.config.shortcut_key,
            double_click_callback=self._on_double_click
        )

        # 菜单项
        self.status_item = rumps.MenuItem("状态: 空闲")
        self.status_item.set_callback(None)
        self.stats_item = rumps.MenuItem("今日: 0 字 | 累计: 0 字")
        self.stats_item.set_callback(None)
        self.menu = [
            self.status_item,
            self.stats_item,
            None,  # 分隔线
            rumps.MenuItem("设置...", callback=self._open_settings),
        ]

        # 初始化统计显示
        self._update_stats_display()

    def _update_status(self, text: str):
        """更新状态栏菜单中的状态文字"""
        self.status_item.title = f"状态: {text}"

    def _update_stats_display(self):
        """更新统计显示"""
        history_mgr = get_history_manager()
        stats = history_mgr.get_stats()
        today_stats = history_mgr.get_today_stats()

        today_chars = today_stats.get("today_chars", 0)
        total_chars = stats.get("total_chars", 0)
        self.stats_item.title = f"今日: {today_chars:,} 字 | 累计: {total_chars:,} 字"

    def _set_state(self, new_state: AppState):
        """设置应用状态"""
        with self._state_lock:
            self.state = new_state

            if new_state == AppState.IDLE:
                self.icon = self.icon_idle
                self._update_status("空闲")
            elif new_state == AppState.RECORDING:
                self.icon = self.icon_recording
                self._update_status("录音中...")
            elif new_state == AppState.PROCESSING:
                self.icon = self.icon_idle
                self._update_status("识别中...")

    def _on_shortcut(self):
        """快捷键回调"""
        with self._state_lock:
            current_state = self.state

        if current_state == AppState.IDLE:
            # 开始录音
            self._start_recording()
        elif current_state == AppState.RECORDING:
            # 停止录音并识别
            self._stop_and_recognize()
        # PROCESSING 状态忽略按键

    def _on_double_click(self):
        """双击快捷键回调 - 用剪贴板更新最新历史"""
        import subprocess

        # 只在 IDLE 状态下响应
        with self._state_lock:
            if self.state != AppState.IDLE:
                return

        # 读取剪贴板
        result = subprocess.run(['pbpaste'], capture_output=True, text=True)
        clipboard_text = result.stdout.strip()

        if not clipboard_text:
            rumps.notification("语音输入", "", "剪贴板为空", sound=False)
            return

        # 更新最新历史（标记为手动覆盖）
        history_mgr = get_history_manager()
        recent = history_mgr.get_recent(1)
        if recent:
            history_mgr.update(recent[0]["timestamp"], clipboard_text, is_manual=True)
            # 更新统计显示
            self._update_stats_display()
            rumps.notification("语音输入", "", "已更新最新历史", sound=False)
        else:
            rumps.notification("语音输入", "", "暂无历史消息", sound=False)

    def _start_recording(self):
        """开始录音"""
        self._set_state(AppState.RECORDING)
        self.recorder.start(
            max_duration=self.config.recording_max_duration,
            silence_timeout=self.config.recording_silence_timeout,
            on_auto_stop=self._on_auto_stop
        )

    def _on_auto_stop(self, reason: str):
        """处理自动停止事件

        Args:
            reason: 停止原因 ('timeout' / 'silence')
        """
        with self._state_lock:
            if self.state != AppState.RECORDING:
                return

        if reason == 'timeout':
            # 超时：停止录音并进行识别
            self._stop_and_recognize()
        elif reason == 'silence':
            # 静音超时：取消录音
            self._set_state(AppState.IDLE)
            self.recorder.stop()  # 停止录音但不处理
            rumps.notification(
                title="语音输入",
                subtitle="",
                message="录音已取消（未检测到声音）",
                sound=False
            )

    def _stop_and_recognize(self):
        """停止录音并进行识别"""
        self._set_state(AppState.PROCESSING)

        # 停止录音
        audio_data = self.recorder.stop()

        if len(audio_data) == 0:
            rumps.notification(
                title="语音输入",
                subtitle="",
                message="没有录到音频",
                sound=False
            )
            self._set_state(AppState.IDLE)
            return

        # 在后台线程进行识别
        threading.Thread(target=self._recognize_and_input, args=(audio_data,), daemon=True).start()

    def _recognize_and_input(self, audio_data):
        """识别并输入文字（在后台线程运行）"""
        try:
            # 转换为 base64
            audio_base64 = audio_to_base64(audio_data)

            if not audio_base64:
                rumps.notification(
                    title="语音输入",
                    subtitle="",
                    message="音频处理失败",
                    sound=False
                )
                self._set_state(AppState.IDLE)
                return

            # 调用 ASR 识别
            original_text = self._recognize_speech(audio_base64)

            # 版本追踪变量
            corrected_text = original_text
            status = "none"

            # 1. 语音纠错（如果启用且长度>=5）
            if original_text and original_text.strip() and len(original_text.strip()) >= 5 and self.config.llm_correction_enabled:
                corrected_text = self._correct_with_llm(original_text)
                if corrected_text != original_text:
                    status = "auto"
                else:
                    status = "unchanged"

            # 2. 上下文纠错（如果启用）
            if corrected_text and corrected_text.strip() and self.config.context_correction_enabled:
                context_corrected = self._correct_with_context(corrected_text)
                if context_corrected != corrected_text:
                    corrected_text = context_corrected
                    status = "auto"

            # 3. 将结果添加到历史（带版本信息）
            final_text = corrected_text
            if final_text and final_text.strip():
                history_mgr = get_history_manager()
                history_mgr.add(
                    original=original_text,
                    corrected=corrected_text if status != "none" else None,
                    text=final_text,
                    status=status
                )
                # 更新统计显示
                self._update_stats_display()

            if final_text:
                # 输入识别的文字
                input_text(final_text)
            else:
                rumps.notification(
                    title="语音输入",
                    subtitle="",
                    message="未识别到文字",
                    sound=False
                )

        except Exception as e:
            rumps.notification(
                title="语音输入",
                subtitle="错误",
                message=str(e)[:100],
                sound=False
            )
        finally:
            self._set_state(AppState.IDLE)

    def _recognize_speech(self, audio_base64: str) -> str:
        """
        调用 ASR 模型进行语音识别

        Args:
            audio_base64: base64 编码的音频数据

        Returns:
            识别出的文字
        """
        # 获取 API Key（优先使用配置文件，其次环境变量）
        api_key = self.config.get_effective_api_key()
        if not api_key:
            raise ValueError("请在设置中配置 API Key 或设置环境变量 DASHSCOPE_API_KEY")

        client = OpenAI(
            api_key=api_key,
            base_url=self.config.asr_base_url
        )

        # 调用 ASR 模型
        completion = client.chat.completions.create(
            model=self.config.asr_model,
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

    def _correct_with_llm(self, text: str) -> str:
        """
        使用 LLM 对语音识别结果进行纠错

        Args:
            text: 语音识别的原始文本

        Returns:
            纠错后的文本
        """
        api_key = self.config.get_effective_llm_api_key()
        if not api_key:
            # 没有配置 LLM API Key，返回原文
            return text

        # 根据 provider 获取 base_url
        provider = self.config.llm_provider
        if provider == "deepseek":
            base_url = "https://api.deepseek.com"
        else:
            base_url = "https://api.deepseek.com"  # 默认使用 deepseek

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        # 构建纠错请求 - 使用 system 角色分离指令和内容
        prompt = self.config.llm_correction_prompt
        try:
            completion = client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                stream=False
            )
            corrected_text = completion.choices[0].message.content
            return corrected_text.strip() if corrected_text else text
        except Exception:
            # 纠错失败，返回原文
            return text

    def _correct_with_context(self, text: str) -> str:
        """
        使用上下文对语音识别结果进行纠错

        Args:
            text: 语音识别的原始文本（可能已经过语音纠错）

        Returns:
            纠错后的文本
        """
        # 获取上下文窗口内的历史消息（带有效期过滤）
        history_mgr = get_history_manager()
        recent = history_mgr.get_recent(
            self.config.context_window_size,
            ttl_minutes=self.config.context_history_ttl
        )
        context_window = [h["text"] for h in recent]
        if not context_window:
            # 没有历史消息，直接返回
            return text

        api_key = self.config.get_effective_llm_api_key()
        if not api_key:
            return text

        # 根据 provider 获取 base_url
        provider = self.config.llm_provider
        if provider == "deepseek":
            base_url = "https://api.deepseek.com"
        else:
            base_url = "https://api.deepseek.com"

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        # 构建历史消息文本
        history_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(context_window)])

        # 获取上下文纠错提示词并填充变量
        prompt_template = self.config.context_correction_prompt
        prompt = prompt_template.format(history=history_text, current=text)

        try:
            completion = client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                stream=False
            )
            corrected_text = completion.choices[0].message.content
            return corrected_text.strip() if corrected_text else text
        except Exception:
            # 纠错失败，返回原文
            return text

    def _start_settings_server(self):
        """在后台启动设置服务"""
        def run_server():
            import uvicorn
            from settings_server import app
            uvicorn.run(app, host="127.0.0.1", port=SETTINGS_PORT, log_level="warning")

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()

    def _start_config_watcher(self):
        """启动配置文件监控"""
        def watch_config():
            import time
            while self._running:
                try:
                    mtime = os.path.getmtime(self.config.config_file)
                    if mtime > self._config_mtime:
                        if self._config_mtime > 0:  # 不是第一次
                            self._reload_config()
                        self._config_mtime = mtime
                except Exception:
                    pass
                time.sleep(1)

        thread = threading.Thread(target=watch_config, daemon=True)
        thread.start()

    def _reload_config(self):
        """重新加载配置"""
        # 重新读取配置
        self.config = get_config()
        self.config._config = self.config._load_config()

        # 更新麦克风设备
        self.recorder.set_device(self.config.microphone_device_id)

    def _open_settings(self, _):
        """打开设置页面"""
        webbrowser.open(f"http://127.0.0.1:{SETTINGS_PORT}/settings")

    def run(self, **options):
        """启动应用"""
        # 启动键盘监听
        self.keyboard_listener.start()

        try:
            super().run(**options)
        finally:
            # 停止运行
            self._running = False
            # 停止键盘监听
            self.keyboard_listener.stop()


def main():
    # 检查 API Key
    config = get_config()
    if not config.get_effective_api_key():
        print("提示: 未配置 API Key")
        print("请在设置中配置，或设置环境变量 DASHSCOPE_API_KEY")
        print("应用仍会启动，但语音识别功能将不可用")

    app = VoiceInputApp()
    app.run()


if __name__ == "__main__":
    main()
