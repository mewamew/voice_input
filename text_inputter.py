"""
文字输入模块 - 通过剪贴板和模拟按键输入文字
"""
import time
from AppKit import NSPasteboard, NSStringPboardType
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    kCGHIDEventTap,
    CGEventSetFlags,
    kCGEventFlagMaskCommand
)


def copy_to_clipboard(text: str) -> bool:
    """
    将文字复制到剪贴板

    Args:
        text: 要复制的文字

    Returns:
        是否成功
    """
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
    # V 键的虚拟键码
    V_KEY_CODE = 9

    # 按下 Command+V
    event_down = CGEventCreateKeyboardEvent(None, V_KEY_CODE, True)
    CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_down)

    # 释放 Command+V
    event_up = CGEventCreateKeyboardEvent(None, V_KEY_CODE, False)
    CGEventSetFlags(event_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_up)


def input_text(text: str) -> bool:
    """
    将文字输入到当前窗口

    通过剪贴板和模拟粘贴实现

    Args:
        text: 要输入的文字

    Returns:
        是否成功
    """
    if not text:
        return False

    # 复制到剪贴板
    if not copy_to_clipboard(text):
        return False

    # 稍微延迟，确保剪贴板已更新
    time.sleep(0.05)

    # 模拟粘贴
    simulate_paste()

    return True


if __name__ == "__main__":
    import sys

    print("测试文字输入模块...")
    print("3秒后将输入测试文字，请点击一个文本输入框...")

    time.sleep(3)

    test_text = "你好，这是语音输入测试！Hello, Voice Input Test!"
    print(f"正在输入: {test_text}")

    if input_text(test_text):
        print("输入成功！")
    else:
        print("输入失败！")
