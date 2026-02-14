"""
浮动文字窗口 - 实时显示语音识别结果

macOS: 使用 AppKit NSWindow（borderless, floating, 鼠标穿透）
"""
import sys
import threading
from typing import Optional


if sys.platform == "darwin":
    from AppKit import (
        NSObject, NSWindow, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSTextField, NSTextFieldCell, NSFont, NSColor,
        NSScreen, NSMakeRect, NSTextAlignmentCenter,
    )
    from objc import super as objc_super

    class _VerticalCenterCell(NSTextFieldCell):
        """垂直居中的 NSTextFieldCell"""

        def drawInteriorWithFrame_inView_(self, frame, view):
            attr_str = self.attributedStringValue()
            text_size = attr_str.size()
            centered = NSMakeRect(
                frame.origin.x,
                frame.origin.y + (frame.size.height - text_size.height) / 2,
                frame.size.width,
                text_size.height,
            )
            objc_super(_VerticalCenterCell, self).drawInteriorWithFrame_inView_(centered, view)

    class _OverlayHelper(NSObject):
        """主线程操作代理（在模块级定义，避免重复注册 ObjC 类）"""

        def initWithOverlay_(self, overlay):
            self = self.init()
            if self is None:
                return None
            self._overlay = overlay
            self._text = ""
            return self

        def performShow_(self, _):
            self._overlay._ensure_init()
            if self._overlay._window:
                if self._text:
                    self._overlay._text_field.setStringValue_(self._text)
                self._overlay._window.orderFront_(None)

        def performHide_(self, _):
            if self._overlay._window:
                self._overlay._window.orderOut_(None)

        def performUpdate_(self, _):
            if self._overlay._text_field:
                self._overlay._text_field.setStringValue_(self._text)


class OverlayWindow:
    """浮动文字窗口（macOS 实现）"""

    def __init__(self):
        self._window = None
        self._text_field = None
        self._initialized = False
        # 保持 helper 引用，防止被 GC
        self._helper = None
        if sys.platform == "darwin":
            self._helper = _OverlayHelper.alloc().initWithOverlay_(self)

    def _ensure_init(self):
        """确保窗口已初始化（必须在主线程调用）"""
        if self._initialized:
            return

        if sys.platform != "darwin":
            return

        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()

        # 窗口尺寸和位置（屏幕底部中央）
        window_width = 600
        window_height = 50
        x = (screen_frame.size.width - window_width) / 2
        y = screen_frame.size.height * 0.15  # 屏幕下方 15% 位置

        rect = NSMakeRect(x, y, window_width, window_height)

        # 创建无边框窗口
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False
        )

        # 设置窗口属性
        window.setLevel_(NSFloatingWindowLevel + 1)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.75))
        window.setIgnoresMouseEvents_(True)  # 鼠标穿透
        window.setHasShadow_(True)

        # 创建圆角内容视图
        content_view = window.contentView()
        content_view.setWantsLayer_(True)
        content_view.layer().setCornerRadius_(12)
        content_view.layer().setMasksToBounds_(True)

        # 创建文本标签（占满窗口高度，通过自定义 Cell 垂直居中）
        text_rect = NSMakeRect(16, 0, window_width - 32, window_height)
        text_field = NSTextField.alloc().initWithFrame_(text_rect)
        text_field.setCell_(_VerticalCenterCell.alloc().init())
        text_field.setStringValue_("")
        text_field.setFont_(NSFont.systemFontOfSize_(18))
        text_field.setTextColor_(NSColor.whiteColor())
        text_field.setBackgroundColor_(NSColor.clearColor())
        text_field.setBezeled_(False)
        text_field.setEditable_(False)
        text_field.setSelectable_(False)
        text_field.setAlignment_(NSTextAlignmentCenter)
        text_field.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail

        content_view.addSubview_(text_field)

        self._window = window
        self._text_field = text_field
        self._initialized = True

    def show(self, text: str = ""):
        """显示浮动窗口"""
        if sys.platform != "darwin" or not self._helper:
            return

        self._helper._text = text
        self._helper.performSelectorOnMainThread_withObject_waitUntilDone_(
            "performShow:", None, False
        )

    def hide(self):
        """隐藏浮动窗口"""
        if sys.platform != "darwin" or not self._helper:
            return

        # waitUntilDone=True 确保在返回前窗口已隐藏
        self._helper.performSelectorOnMainThread_withObject_waitUntilDone_(
            "performHide:", None, True
        )

    def update_text(self, text: str):
        """更新显示文字（线程安全）"""
        if sys.platform != "darwin" or not self._helper:
            return

        self._helper._text = text
        self._helper.performSelectorOnMainThread_withObject_waitUntilDone_(
            "performUpdate:", None, False
        )
