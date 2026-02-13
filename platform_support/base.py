"""
平台抽象基类 - 定义跨平台应用接口
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Optional, List, Tuple


class AppState(Enum):
    """应用状态"""
    IDLE = "idle"           # 空闲
    RECORDING = "recording" # 录音中
    PROCESSING = "processing"  # 识别处理中


class MenuItem:
    """菜单项"""
    def __init__(self, title: str, callback: Callable = None, enabled: bool = True):
        self.title = title
        self.callback = callback
        self.enabled = enabled


class BasePlatformApp(ABC):
    """平台应用抽象基类"""

    def __init__(self, name: str, icon_idle: str, icon_recording: str):
        """
        初始化应用

        Args:
            name: 应用名称
            icon_idle: 空闲状态图标路径
            icon_recording: 录音状态图标路径
        """
        self.name = name
        self.icon_idle = icon_idle
        self.icon_recording = icon_recording
        self.state = AppState.IDLE
        self._menu_items: List[MenuItem] = []

    @abstractmethod
    def set_icon(self, icon_path: str):
        """设置托盘图标"""
        pass

    @abstractmethod
    def set_menu(self, items: List[MenuItem]):
        """设置菜单项"""
        pass

    @abstractmethod
    def update_menu_item(self, index: int, title: str = None, enabled: bool = None):
        """更新菜单项"""
        pass

    @abstractmethod
    def show_notification(self, title: str, subtitle: str, message: str, sound: bool = False):
        """显示通知"""
        pass

    @abstractmethod
    def run(self):
        """启动应用主循环"""
        pass

    @abstractmethod
    def quit(self):
        """退出应用"""
        pass

    def set_state(self, new_state: AppState):
        """设置应用状态"""
        self.state = new_state
        if new_state == AppState.IDLE:
            self.set_icon(self.icon_idle)
        elif new_state == AppState.RECORDING:
            self.set_icon(self.icon_recording)
        elif new_state == AppState.PROCESSING:
            self.set_icon(self.icon_idle)


class BaseTextInputter(ABC):
    """文本输入抽象基类"""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> bool:
        """复制文本到剪贴板"""
        pass

    @abstractmethod
    def paste(self) -> bool:
        """模拟粘贴操作"""
        pass

    @abstractmethod
    def read_clipboard(self) -> str:
        """读取剪贴板内容"""
        pass

    def input_text(self, text: str) -> bool:
        """输入文本（复制+粘贴）"""
        if not text:
            return False
        if not self.copy_to_clipboard(text):
            return False
        import time
        time.sleep(0.05)
        return self.paste()
