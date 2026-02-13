"""
Windows 平台实现 - 使用 pystray, pyperclip, pyautogui, plyer
"""
import os
import time
import threading
from typing import List, Callable, Optional

try:
    import pystray
    from PIL import Image
    import pyperclip
    import pyautogui
    from plyer import notification as plyer_notification
    WINDOWS_DEPS_AVAILABLE = True
except ImportError:
    WINDOWS_DEPS_AVAILABLE = False

from .base import BasePlatformApp, AppState, MenuItem


def copy_to_clipboard(text: str) -> bool:
    """将文字复制到剪贴板"""
    try:
        pyperclip.copy(text)
        return True
    except Exception as e:
        print(f"复制到剪贴板失败: {e}")
        return False


def simulate_paste():
    """模拟 Ctrl+V 粘贴操作"""
    pyautogui.hotkey('ctrl', 'v')


def input_text(text: str) -> bool:
    """将文字输入到当前窗口"""
    if not text:
        return False
    if not copy_to_clipboard(text):
        return False
    time.sleep(0.05)
    simulate_paste()
    return True


def read_clipboard() -> str:
    """读取剪贴板内容"""
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def show_notification(title: str, subtitle: str, message: str, sound: bool = False):
    """显示系统通知"""
    try:
        # 合并 subtitle 和 message
        full_message = f"{subtitle}\n{message}" if subtitle else message
        plyer_notification.notify(
            title=title,
            message=full_message,
            app_name="语音输入",
            timeout=5
        )
    except Exception as e:
        print(f"[通知] {title}: {message}")


class WindowsApp(BasePlatformApp):
    """Windows 托盘应用实现"""

    def __init__(self, name: str, icon_idle: str, icon_recording: str,
                 on_quit: Callable = None):
        super().__init__(name, icon_idle, icon_recording)
        self._on_quit = on_quit
        self._icon: Optional[pystray.Icon] = None
        self._menu_callbacks = {}
        self._status_text = "空闲"
        self._stats_text = "今日: 0 字 | 累计: 0 字"
        self._record_text = "开始录音"
        self._on_toggle_recording: Optional[Callable] = None
        self._on_open_settings: Optional[Callable] = None
        self._running = False

    def _load_icon(self, icon_path: str) -> Image.Image:
        """加载图标文件"""
        if os.path.exists(icon_path):
            return Image.open(icon_path)
        # 创建默认图标
        img = Image.new('RGB', (64, 64), color='gray')
        return img

    def _create_menu(self) -> pystray.Menu:
        """创建菜单"""
        return pystray.Menu(
            pystray.MenuItem(f"状态: {self._status_text}", None, enabled=False),
            pystray.MenuItem(self._stats_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._record_text,
                lambda: self._on_toggle_recording(None) if self._on_toggle_recording else None
            ),
            pystray.MenuItem(
                "设置...",
                lambda: self._on_open_settings(None) if self._on_open_settings else None
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit_app),
        )

    def _update_menu(self):
        """更新菜单（需要重建）"""
        if self._icon:
            self._icon.menu = self._create_menu()

    def set_icon(self, icon_path: str):
        """设置托盘图标"""
        if self._icon:
            self._icon.icon = self._load_icon(icon_path)

    def set_menu(self, items: List[MenuItem]):
        """设置菜单项"""
        self._menu_items = items

    def update_menu_item(self, index: int, title: str = None, enabled: bool = None):
        """更新菜单项"""
        # pystray 需要重建菜单来更新
        self._update_menu()

    def update_status(self, text: str):
        """更新状态文字"""
        self._status_text = text
        self._update_menu()

    def update_stats(self, today_chars: int, total_chars: int):
        """更新统计显示"""
        self._stats_text = f"今日: {today_chars:,} 字 | 累计: {total_chars:,} 字"
        self._update_menu()

    def update_record_button(self, title: str):
        """更新录音按钮文字"""
        self._record_text = title
        self._update_menu()

    def show_notification(self, title: str, subtitle: str, message: str, sound: bool = False):
        """显示系统通知"""
        show_notification(title, subtitle, message, sound)

    def setup_menu(self, on_toggle_recording: Callable, on_open_settings: Callable):
        """设置标准菜单

        Args:
            on_toggle_recording: 录音按钮回调
            on_open_settings: 设置按钮回调
        """
        self._on_toggle_recording = on_toggle_recording
        self._on_open_settings = on_open_settings

    def set_state(self, new_state: AppState):
        """设置应用状态"""
        super().set_state(new_state)

        if new_state == AppState.IDLE:
            self.update_status("空闲")
            self.update_record_button("开始录音")
        elif new_state == AppState.RECORDING:
            self.update_status("录音中...")
            self.update_record_button("结束录音")
        elif new_state == AppState.PROCESSING:
            self.update_status("识别中...")
            self.update_record_button("识别中...")

    def _quit_app(self):
        """退出应用"""
        self._running = False
        if self._on_quit:
            self._on_quit()
        if self._icon:
            self._icon.stop()

    def run(self):
        """启动应用"""
        self._running = True
        icon_image = self._load_icon(self.icon_idle)
        self._icon = pystray.Icon(
            name=self.name,
            icon=icon_image,
            title=self.name,
            menu=self._create_menu()
        )
        self._icon.run()

    def quit(self):
        """退出应用"""
        self._quit_app()
