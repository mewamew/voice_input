"""
语音输入法 - 跨平台状态栏/托盘应用

使用可配置的快捷键触发录音，自动识别并输入文字
支持 macOS 和 Windows
"""
import os
import sys
import threading
import webbrowser

from openai import OpenAI

from keyboard_listener import KeyboardListener, get_default_shortcut
from audio_recorder import AudioRecorder, audio_to_base64
from config_manager import get_config, get_history_manager
from platform_support import IS_MACOS, IS_WINDOWS, get_platform_app, show_notification
from platform_support.base import AppState
from overlay_window import OverlayWindow

# 设置服务端口
SETTINGS_PORT = 18321


class VoiceInputApp:
    """语音输入应用（跨平台）"""

    def __init__(self):
        # 获取脚本所在目录
        self.app_dir = os.path.dirname(os.path.abspath(__file__))

        # 图标路径
        self.icon_idle = os.path.join(self.app_dir, "microphone.slash.png")
        self.icon_recording = os.path.join(self.app_dir, "microphone.png")

        # 配置
        self.config = get_config()
        self._config_mtime = 0

        # 运行标志
        self._running = True

        # 状态
        self.state = AppState.IDLE
        self._state_lock = threading.Lock()

        # 录音器
        self.recorder = AudioRecorder(device_id=self.config.microphone_device_id)

        # 流式识别相关
        self._streaming_asr = None
        self._streaming_lock = threading.Lock()  # 保护 _streaming_asr 的并发访问
        self._streaming_last_text = ""  # 追踪流式识别最新文字
        self._streaming_text_lock = threading.Lock()
        self._overlay = OverlayWindow()

        # 键盘监听器
        self.keyboard_listener = KeyboardListener(
            callback=self._on_shortcut,
            shortcut_key=self.config.shortcut_key,
            double_click_callback=self._on_double_click,
            should_handle_double_click=self._can_handle_double_click
        )

        # 创建平台应用
        PlatformApp = get_platform_app()
        self.platform_app = PlatformApp(
            name="语音输入",
            icon_idle=self.icon_idle,
            icon_recording=self.icon_recording,
            on_quit=self._on_quit
        )

    def _on_quit(self):
        """退出回调"""
        self._running = False
        self.keyboard_listener.stop()
        # 确保录音器和流式 ASR 被清理
        try:
            self.recorder.stop()
        except Exception:
            pass
        with self._streaming_lock:
            streaming_asr = self._streaming_asr
            self._streaming_asr = None
        if streaming_asr:
            try:
                streaming_asr.stop()
            except Exception:
                pass

    def _update_stats_display(self):
        """更新统计显示"""
        history_mgr = get_history_manager()
        stats = history_mgr.get_stats()
        today_stats = history_mgr.get_today_stats()

        today_chars = today_stats.get("today_chars", 0)
        total_chars = stats.get("total_chars", 0)
        self.platform_app.update_stats(today_chars, total_chars)

    def _set_state(self, new_state: AppState):
        """设置应用状态"""
        with self._state_lock:
            self.state = new_state
            self.platform_app.set_state(new_state)

    def _toggle_recording(self, _):
        """菜单录音按钮回调"""
        self._on_shortcut()

    def _on_shortcut(self):
        """快捷键回调"""
        with self._state_lock:
            current_state = self.state

        # 自愈：状态显示为录音中，但录音器已经不在录音时，先回到空闲状态
        if current_state == AppState.RECORDING and not self.recorder.is_recording():
            self._set_state(AppState.IDLE)
            return

        if current_state == AppState.IDLE:
            self._start_recording()
        elif current_state == AppState.RECORDING:
            self._stop_and_recognize()

    def _can_handle_double_click(self) -> bool:
        """仅在空闲状态下启用双击功能"""
        with self._state_lock:
            return self.state == AppState.IDLE

    def _on_double_click(self):
        """双击快捷键回调 - 用剪贴板更新最新历史"""
        with self._state_lock:
            if self.state != AppState.IDLE:
                return

        # 读取剪贴板
        from platform_support import get_clipboard_reader
        read_clipboard = get_clipboard_reader()
        clipboard_text = read_clipboard()

        if not clipboard_text:
            self.platform_app.show_notification("语音输入", "", "剪贴板为空", sound=False)
            return

        # 更新最新历史
        history_mgr = get_history_manager()
        recent = history_mgr.get_recent(1)
        if recent:
            history_mgr.update(recent[0]["timestamp"], clipboard_text, is_manual=True)
            self._update_stats_display()
            self.platform_app.show_notification("语音输入", "", "已更新最新历史", sound=False)
        else:
            self.platform_app.show_notification("语音输入", "", "暂无历史消息", sound=False)

    def _start_recording(self):
        """开始录音"""
        self._set_state(AppState.RECORDING)

        if self.config.asr_provider == "volcengine":
            self._start_streaming_recording()
        else:
            self._start_batch_recording()

    def _start_batch_recording(self):
        """批处理模式录音（DashScope）"""
        try:
            self.recorder.start(
                max_duration=self.config.recording_max_duration,
                silence_timeout=self.config.recording_silence_timeout,
                on_auto_stop=self._on_auto_stop
            )
        except Exception as e:
            self._set_state(AppState.IDLE)
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="",
                message=f"无法开始录音: {str(e)[:80]}",
                sound=False
            )

    def _start_streaming_recording(self):
        """流式模式录音（火山引擎）"""
        asr = None
        try:
            from volcengine_asr import VolcengineStreamingASR

            keys = self.config.get_effective_volcengine_keys()
            if not keys["app_key"] or not keys["access_key"]:
                raise ValueError("请在设置中配置火山引擎 App Key 和 Access Key")

            # 创建流式 ASR 客户端
            asr = VolcengineStreamingASR(
                app_key=keys["app_key"],
                access_key=keys["access_key"],
                on_partial_result=self._on_streaming_partial,
                on_final_result=self._on_streaming_final,
                on_error=self._on_streaming_error,
            )
            asr.start()

            with self._streaming_lock:
                self._streaming_asr = asr

            # 重置流式识别文字追踪
            with self._streaming_text_lock:
                self._streaming_last_text = ""

            # 显示浮动窗口
            self._overlay.show("正在聆听...")

            # 开始录音，音频数据通过回调转发给 ASR
            self.recorder.start(
                max_duration=self.config.recording_max_duration,
                silence_timeout=self.config.recording_silence_timeout,
                on_auto_stop=self._on_auto_stop,
                on_audio_chunk=asr.feed_audio,
            )
        except Exception as e:
            if asr:
                # recorder.start 失败时，asr 线程可能已启动，异步收尾避免会话泄漏
                threading.Thread(target=asr.stop, daemon=True).start()
            with self._streaming_lock:
                self._streaming_asr = None
            self._overlay.hide()
            self._set_state(AppState.IDLE)
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="",
                message=f"流式识别启动失败: {str(e)[:80]}",
                sound=False
            )

    def _on_streaming_partial(self, text: str):
        """流式识别中间结果回调"""
        if text:
            with self._streaming_text_lock:
                self._streaming_last_text = text
        self._overlay.update_text(text if text else "正在聆听...")

    def _on_streaming_final(self, text: str):
        """流式识别最终结果回调"""
        if text:
            with self._streaming_text_lock:
                self._streaming_last_text = text
            self._overlay.update_text(text)

    def _on_streaming_error(self, msg: str):
        """流式识别错误回调"""
        # 解析错误类型
        error_type = "UNKNOWN"
        error_message = msg

        if msg.startswith("BUFFER_FULL_AUTO_STOP:"):
            error_type = "BUFFER_FULL"
            error_message = msg.split(":", 1)[1] if ":" in msg else msg
        elif msg.startswith("BUFFER_WARNING:"):
            error_type = "BUFFER_WARNING"
            error_message = msg.split(":", 1)[1] if ":" in msg else msg

        # 缓冲区预警：只通知，不停止
        if error_type == "BUFFER_WARNING":
            self._overlay.update_text("网络延迟较高...")
            # 不需要额外处理，继续录音
            return

        # 缓冲区满：自动停止录音
        if error_type == "BUFFER_FULL":
            with self._state_lock:
                current_state = self.state

            if current_state == AppState.RECORDING:
                # 更新浮动窗口提示
                self._overlay.update_text("网络延迟过高，正在停止...")

                # 异步触发停止流程，处理已录制内容
                def auto_stop_on_buffer_full():
                    # 停止录音并处理已有音频
                    self._stop_and_recognize()

                    # 显示明确的通知
                    self.platform_app.show_notification(
                        title="语音输入",
                        subtitle="",
                        message="网络延迟过高，录音已自动停止，正在处理已录制内容",
                        sound=False
                    )

                threading.Thread(target=auto_stop_on_buffer_full, daemon=True).start()
                return

        # 其他错误：原有逻辑
        self._overlay.update_text("识别出错，正在结束...")

        with self._state_lock:
            current_state = self.state
        with self._streaming_lock:
            has_streaming = self._streaming_asr is not None

        if current_state == AppState.RECORDING and has_streaming:
            # 网络/服务端异常时，自动走停录流程，尽量输出已有 partial
            threading.Thread(target=self._stop_and_recognize, daemon=True).start()
            return

        if current_state != AppState.PROCESSING:
            self._overlay.hide()
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="",
                message=f"流式识别异常: {error_message[:80]}",
                sound=False
            )
            self._set_state(AppState.IDLE)

    def _on_auto_stop(self, reason: str):
        """处理自动停止事件"""
        with self._state_lock:
            if self.state != AppState.RECORDING:
                return

        if reason == 'timeout':
            self._stop_and_recognize()
        elif reason == 'silence':
            with self._streaming_lock:
                is_streaming = self._streaming_asr is not None

            if is_streaming:
                # 流式模式：交给 _stop_and_recognize 处理，等待 ASR 最终结果
                self._stop_and_recognize()
            else:
                # 批处理模式：直接取消录音
                self.recorder.stop()
                self._set_state(AppState.IDLE)
                self.platform_app.show_notification(
                    title="语音输入",
                    subtitle="",
                    message="录音已取消（未检测到声音）",
                    sound=False
                )

    def _stop_and_recognize(self):
        """停止录音并进行识别"""
        self._set_state(AppState.PROCESSING)

        # 先停录音器（立即释放麦克风）
        try:
            audio_data = self.recorder.stop()
        except Exception as e:
            self._overlay.hide()
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="",
                message=f"停止录音失败: {str(e)[:80]}",
                sound=False
            )
            self._set_state(AppState.IDLE)
            return

        # 取出流式 ASR（加锁防止和 auto-stop 竞态）
        with self._streaming_lock:
            streaming_asr = self._streaming_asr
            self._streaming_asr = None

        # 流式模式：停止 ASR 并等待最终结果
        if streaming_asr:
            self._overlay.update_text("正在处理...")

            def finalize_streaming():
                try:
                    final_text = streaming_asr.stop()
                    # 服务端未返回 final 时，回退到最近一次 partial，避免静音自动停止后丢半句
                    if not final_text or not final_text.strip():
                        with self._streaming_text_lock:
                            final_text = self._streaming_last_text
                    self._overlay.hide()

                    if final_text and final_text.strip():
                        self._correct_and_input(final_text)
                    else:
                        self.platform_app.show_notification(
                            title="语音输入",
                            subtitle="",
                            message="未识别到文字",
                            sound=False
                        )
                        self._set_state(AppState.IDLE)
                except Exception as e:
                    self._overlay.hide()
                    self.platform_app.show_notification(
                        title="语音输入",
                        subtitle="错误",
                        message=str(e)[:100],
                        sound=False
                    )
                    self._set_state(AppState.IDLE)

            threading.Thread(target=finalize_streaming, daemon=True).start()
            return

        # 批处理模式
        if len(audio_data) == 0:
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="",
                message="没有录到音频",
                sound=False
            )
            self._set_state(AppState.IDLE)
            return

        threading.Thread(target=self._recognize_and_input, args=(audio_data,), daemon=True).start()

    def _recognize_and_input(self, audio_data):
        """识别并输入文字（批处理模式，在后台线程运行）"""
        try:
            audio_base64 = audio_to_base64(audio_data)

            if not audio_base64:
                self.platform_app.show_notification(
                    title="语音输入",
                    subtitle="",
                    message="音频处理失败",
                    sound=False
                )
                self._set_state(AppState.IDLE)
                return

            original_text = self._recognize_speech(audio_base64)
            self._correct_and_input(original_text)

        except Exception as e:
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="错误",
                message=str(e)[:100],
                sound=False
            )
            self._set_state(AppState.IDLE)

    def _correct_and_input(self, original_text: str):
        """纠错并输入文字（批处理和流式模式共用）"""
        try:
            corrected_text = original_text
            status = "none"

            # 语音纠错
            if original_text and original_text.strip() and len(original_text.strip()) >= 5 and self.config.llm_correction_enabled:
                corrected_text = self._correct_with_llm(original_text)
                if corrected_text != original_text:
                    status = "auto"
                else:
                    status = "unchanged"

            # 上下文纠错
            if corrected_text and corrected_text.strip() and self.config.context_correction_enabled:
                context_corrected = self._correct_with_context(corrected_text)
                if context_corrected != corrected_text:
                    corrected_text = context_corrected
                    status = "auto"

            # 添加到历史
            final_text = corrected_text
            if final_text and final_text.strip():
                history_mgr = get_history_manager()
                history_mgr.add(
                    original=original_text,
                    corrected=corrected_text if status != "none" else None,
                    text=final_text,
                    status=status
                )
                self._update_stats_display()

            if final_text:
                from platform_support import get_text_inputter
                input_text = get_text_inputter()
                input_text(final_text)
            else:
                self.platform_app.show_notification(
                    title="语音输入",
                    subtitle="",
                    message="未识别到文字",
                    sound=False
                )

        except Exception as e:
            self.platform_app.show_notification(
                title="语音输入",
                subtitle="错误",
                message=str(e)[:100],
                sound=False
            )
        finally:
            self._set_state(AppState.IDLE)

    def _recognize_speech(self, audio_base64: str) -> str:
        """调用 ASR 模型进行语音识别"""
        api_key = self.config.get_effective_api_key()
        if not api_key:
            raise ValueError("请在设置中配置 API Key 或设置环境变量 DASHSCOPE_API_KEY")

        client = OpenAI(
            api_key=api_key,
            base_url=self.config.asr_base_url
        )

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
        """使用 LLM 对语音识别结果进行纠错"""
        api_key = self.config.get_effective_llm_api_key()
        if not api_key:
            return text

        provider = self.config.llm_provider
        if provider == "deepseek":
            base_url = "https://api.deepseek.com"
        else:
            base_url = "https://api.deepseek.com"

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        prompt = self.config.llm_correction_prompt
        try:
            completion = client.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text}
                ],
                stream=False
            )
            corrected_text = completion.choices[0].message.content
            return corrected_text.strip() if corrected_text else text
        except Exception:
            return text

    def _correct_with_context(self, text: str) -> str:
        """使用上下文对语音识别结果进行纠错"""
        history_mgr = get_history_manager()
        recent = history_mgr.get_recent(
            self.config.context_window_size,
            ttl_minutes=self.config.context_history_ttl
        )
        context_window = [h["text"] for h in recent]
        if not context_window:
            return text

        api_key = self.config.get_effective_llm_api_key()
        if not api_key:
            return text

        provider = self.config.llm_provider
        if provider == "deepseek":
            base_url = "https://api.deepseek.com"
        else:
            base_url = "https://api.deepseek.com"

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        history_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(context_window)])
        prompt_template = self.config.context_correction_prompt
        prompt = prompt_template.format(history=history_text, current=text)

        try:
            completion = client.chat.completions.create(
                model=self.config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            corrected_text = completion.choices[0].message.content
            return corrected_text.strip() if corrected_text else text
        except Exception:
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
                        if self._config_mtime > 0:
                            self._reload_config()
                        self._config_mtime = mtime
                except Exception:
                    pass
                time.sleep(1)

        thread = threading.Thread(target=watch_config, daemon=True)
        thread.start()

    def _reload_config(self):
        """重新加载配置"""
        self.config = get_config()
        self.config._config = self.config._load_config()
        self.recorder.set_device(self.config.microphone_device_id)
        # 更新快捷键监听
        self.keyboard_listener.set_shortcut(self.config.shortcut_key)

    def _open_settings(self, _):
        """打开设置页面"""
        webbrowser.open(f"http://127.0.0.1:{SETTINGS_PORT}/settings")

    def run(self):
        """启动应用"""
        # 启动设置服务
        self._start_settings_server()

        # 启动配置监控
        self._start_config_watcher()

        # 设置菜单
        self.platform_app.setup_menu(
            on_toggle_recording=self._toggle_recording,
            on_open_settings=self._open_settings
        )

        # 初始化统计显示
        self._update_stats_display()

        # 启动键盘监听
        self.keyboard_listener.start()

        try:
            self.platform_app.run()
        finally:
            self._running = False
            self.keyboard_listener.stop()


def main():
    config = get_config()
    if not config.get_effective_api_key():
        print("提示: 未配置 API Key")
        print("请在设置中配置，或设置环境变量 DASHSCOPE_API_KEY")
        print("应用仍会启动，但语音识别功能将不可用")

    app = VoiceInputApp()
    app.run()


if __name__ == "__main__":
    main()
