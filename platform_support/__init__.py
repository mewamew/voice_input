"""
平台抽象层 - 自动检测平台并导入对应实现
"""
import sys

# 平台检测
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def get_platform_name() -> str:
    """获取当前平台名称"""
    if IS_MACOS:
        return "macOS"
    elif IS_WINDOWS:
        return "Windows"
    elif IS_LINUX:
        return "Linux"
    else:
        return "Unknown"


def get_platform_app():
    """获取当前平台的应用类"""
    if IS_MACOS:
        from .macos import MacOSApp
        return MacOSApp
    elif IS_WINDOWS:
        from .windows import WindowsApp
        return WindowsApp
    else:
        raise NotImplementedError(f"不支持的平台: {sys.platform}")


def get_text_inputter():
    """获取当前平台的文本输入函数"""
    if IS_MACOS:
        from .macos import input_text
        return input_text
    elif IS_WINDOWS:
        from .windows import input_text
        return input_text
    else:
        raise NotImplementedError(f"不支持的平台: {sys.platform}")


def get_clipboard_reader():
    """获取当前平台的剪贴板读取函数"""
    if IS_MACOS:
        from .macos import read_clipboard
        return read_clipboard
    elif IS_WINDOWS:
        from .windows import read_clipboard
        return read_clipboard
    else:
        raise NotImplementedError(f"不支持的平台: {sys.platform}")


def show_notification(title: str, subtitle: str, message: str, sound: bool = False):
    """显示系统通知"""
    if IS_MACOS:
        from .macos import show_notification as _show
    elif IS_WINDOWS:
        from .windows import show_notification as _show
    else:
        # 回退：打印到控制台
        print(f"[通知] {title}: {message}")
        return

    _show(title, subtitle, message, sound)
