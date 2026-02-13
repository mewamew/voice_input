"""
macOS 平台实现 - 使用 rumps 和 AppKit/Quartz
"""
import os
import time
import threading
import webbrowser
from typing import List, Callable, Optional

# 隐藏 Dock 图标（必须在导入 rumps 之前设置）
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

import rumps
from AppKit import NSPasteboard, NSStringPboardType
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    kCGHIDEventTap,
    CGEventSetFlags,
    kCGEventFlagMaskCommand
)

from .base import BasePlatformApp, AppState, MenuItem


def copy_to_clipboard(text: str) -> bool:
    """将文字复制到剪贴板"""
    try:
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSStringPboardType)
        return True
    except Exception as e:
        print(f"复制到剪贴板失败: {e}")
        return False


def simulate_paste():
    """模拟 Command+V 粘贴操作"""
    V_KEY_CODE = 9
    event_down = CGEventCreateKeyboardEvent(None, V_KEY_CODE, True)
    CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_down)
    event_up = CGEventCreateKeyboardEvent(None, V_KEY_CODE, False)
    CGEventSetFlags(event_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_up)


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
    import subprocess
    result = subprocess.run(['pbpaste'], capture_output=True, text=True)
    return result.stdout.strip()


def show_notification(title: str, subtitle: str, message: str, sound: bool = False):
    """显示系统通知"""
    rumps.notification(title=title, subtitle=subtitle, message=message, sound=sound)


class MacOSApp(BasePlatformApp):
    """macOS 托盘应用实现"""

    def __init__(self, name: str, icon_idle: str, icon_recording: str,
                 on_quit: Callable = None):
        super().__init__(name, icon_idle, icon_recording)
        self._on_quit = on_quit
        self._rumps_app: Optional[rumps.App] = None
        self._menu_callbacks = {}
        self._status_item: Optional[rumps.MenuItem] = None
        self._stats_item: Optional[rumps.MenuItem] = None
        self._record_item: Optional[rumps.MenuItem] = None

    def _create_rumps_app(self):
        """创建 rumps 应用"""
        self._rumps_app = rumps.App(
            name=self.name,
            icon=self.icon_idle,
            template=True,
            quit_button="退出"
        )

    def set_icon(self, icon_path: str):
        """设置托盘图标"""
        if self._rumps_app:
            self._rumps_app.icon = icon_path

    def set_menu(self, items: List[MenuItem]):
        """设置菜单项"""
        self._menu_items = items
        if not self._rumps_app:
            return

        menu = []
        for i, item in enumerate(items):
            if item is None:
                menu.append(None)  # 分隔线
            else:
                menu_item = rumps.MenuItem(item.title)
                if item.callback:
                    self._menu_callbacks[i] = item.callback
                    menu_item.set_callback(lambda sender, idx=i: self._menu_callbacks[idx](sender))
                else:
                    menu_item.set_callback(None)
                menu.append(menu_item)

        self._rumps_app.menu = menu

    def update_menu_item(self, index: int, title: str = None, enabled: bool = None):
        """更新菜单项"""
        if self._rumps_app and 0 <= index < len(self._rumps_app.menu):
            keys = list(self._rumps_app.menu.keys())
            if index < len(keys):
                menu_item = self._rumps_app.menu[keys[index]]
                if title is not None:
                    menu_item.title = title
                # rumps 菜单项没有直接的 enabled 属性

    def update_status(self, text: str):
        """更新状态文字"""
        if self._status_item:
            self._status_item.title = f"状态: {text}"

    def update_stats(self, today_chars: int, total_chars: int):
        """更新统计显示"""
        if self._stats_item:
            self._stats_item.title = f"今日: {today_chars:,} 字 | 累计: {total_chars:,} 字"

    def update_record_button(self, title: str):
        """更新录音按钮文字"""
        if self._record_item:
            self._record_item.title = title

    def show_notification(self, title: str, subtitle: str, message: str, sound: bool = False):
        """显示系统通知"""
        rumps.notification(title=title, subtitle=subtitle, message=message, sound=sound)

    def setup_menu(self, on_toggle_recording: Callable, on_open_settings: Callable):
        """设置标准菜单

        Args:
            on_toggle_recording: 录音按钮回调
            on_open_settings: 设置按钮回调
        """
        # 确保 rumps_app 已创建
        if not self._rumps_app:
            self._create_rumps_app()

        self._status_item = rumps.MenuItem("状态: 空闲")
        self._status_item.set_callback(None)

        self._stats_item = rumps.MenuItem("今日: 0 字 | 累计: 0 字")
        self._stats_item.set_callback(None)

        self._record_item = rumps.MenuItem("开始录音", callback=on_toggle_recording)

        settings_item = rumps.MenuItem("设置...", callback=on_open_settings)

        self._rumps_app.menu = [
            self._status_item,
            self._stats_item,
            None,
            self._record_item,
            settings_item,
        ]

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

    def run(self):
        """启动应用"""
        if not self._rumps_app:
            self._create_rumps_app()
        self._rumps_app.run()

    def quit(self):
        """退出应用"""
        if self._on_quit:
            self._on_quit()
        if self._rumps_app:
            rumps.quit_application()
