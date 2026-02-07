"""
键盘监听模块 - 监听可配置的快捷键
"""
import time
import threading
from pynput import keyboard
from typing import Callable, Optional


# 双击检测间隔（秒）
DOUBLE_CLICK_INTERVAL = 0.4

# 快捷键映射
SHORTCUT_KEY_MAP = {
    "cmd_r": keyboard.Key.cmd_r,
    "cmd_l": keyboard.Key.cmd_l,
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "alt_r": keyboard.Key.alt_r,
    "alt_l": keyboard.Key.alt_l,
    "shift_r": keyboard.Key.shift_r,
    "shift_l": keyboard.Key.shift_l,
    "caps_lock": keyboard.Key.caps_lock,
    "space": keyboard.Key.space,
    "tab": keyboard.Key.tab,
    "f1": keyboard.Key.f1,
    "f2": keyboard.Key.f2,
    "f3": keyboard.Key.f3,
    "f4": keyboard.Key.f4,
    "f5": keyboard.Key.f5,
    "f6": keyboard.Key.f6,
    "f7": keyboard.Key.f7,
    "f8": keyboard.Key.f8,
    "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10,
    "f11": keyboard.Key.f11,
    "f12": keyboard.Key.f12,
    "fn": keyboard.Key.f20,
}


class KeyboardListener:
    """监听可配置的快捷键"""

    # 时间阈值（秒）
    MIN_PRESS_TIME = 0.05   # 最短按下时间 50ms，避免误触
    MAX_PRESS_TIME = 0.5    # 最长按下时间 500ms，超过认为是长按

    def __init__(self, callback: Callable, shortcut_key: str = "cmd_r",
                 double_click_callback: Callable = None):
        """
        Args:
            callback: 快捷键触发时的回调函数
            shortcut_key: 快捷键标识（如 "cmd_r", "ctrl_l" 等）
            double_click_callback: 双击快捷键时的回调函数
        """
        self.callback = callback
        self.double_click_callback = double_click_callback
        self.listener = None

        # 当前监听的快捷键
        self._shortcut_key = shortcut_key
        self._target_key = SHORTCUT_KEY_MAP.get(shortcut_key, keyboard.Key.cmd_r)

        # 状态跟踪
        self._key_pressed = False
        self._key_press_time = 0
        self._other_key_pressed = False
        self._last_release_time = 0  # 上一次释放时间，用于双击检测
        self._pending_single_click = None  # 待执行的单击定时器
        self._lock = threading.Lock()

    def set_shortcut(self, shortcut_key: str):
        """更新快捷键"""
        with self._lock:
            self._shortcut_key = shortcut_key
            self._target_key = SHORTCUT_KEY_MAP.get(shortcut_key, keyboard.Key.cmd_r)
            # 重置状态
            self._key_pressed = False
            self._key_press_time = 0
            self._other_key_pressed = False
            self._last_release_time = 0
            if self._pending_single_click:
                self._pending_single_click.cancel()
                self._pending_single_click = None

    def start(self):
        """启动键盘监听"""
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self.listener.start()

    def stop(self):
        """停止键盘监听"""
        if self._pending_single_click:
            self._pending_single_click.cancel()
            self._pending_single_click = None
        if self.listener:
            self.listener.stop()
            self.listener = None

    def _on_press(self, key):
        """按键按下事件"""
        with self._lock:
            # 检测目标快捷键
            if key == self._target_key:
                if not self._key_pressed:
                    self._key_pressed = True
                    self._key_press_time = time.time()
                    self._other_key_pressed = False
            else:
                # 其他键被按下
                if self._key_pressed:
                    self._other_key_pressed = True

    def _on_release(self, key):
        """按键释放事件"""
        with self._lock:
            if key == self._target_key and self._key_pressed:
                press_duration = time.time() - self._key_press_time

                # 检查是否为有效的单独按下
                if (not self._other_key_pressed and
                    self.MIN_PRESS_TIME <= press_duration <= self.MAX_PRESS_TIME):
                    current_time = time.time()

                    if current_time - self._last_release_time <= DOUBLE_CLICK_INTERVAL:
                        # 双击检测：取消待执行的单击，执行双击回调
                        if self._pending_single_click:
                            self._pending_single_click.cancel()
                            self._pending_single_click = None
                        self._last_release_time = 0  # 重置，避免三击
                        if self.double_click_callback:
                            threading.Thread(target=self.double_click_callback, daemon=True).start()
                    else:
                        # 可能是单击：延迟执行，等待看是否有双击
                        self._last_release_time = current_time
                        # 取消之前的待执行单击（如果有）
                        if self._pending_single_click:
                            self._pending_single_click.cancel()
                        # 延迟执行单击回调
                        self._pending_single_click = threading.Timer(
                            DOUBLE_CLICK_INTERVAL,
                            self._execute_single_click
                        )
                        self._pending_single_click.start()

                # 重置状态
                self._key_pressed = False
                self._key_press_time = 0
                self._other_key_pressed = False

    def _execute_single_click(self):
        """执行单击回调"""
        with self._lock:
            self._pending_single_click = None
        threading.Thread(target=self.callback, daemon=True).start()


# 保留旧的类名作为别名，保持向后兼容
RightCommandListener = KeyboardListener


if __name__ == "__main__":
    # 测试代码
    def on_shortcut():
        print("快捷键被触发！")

    print("开始监听 Right Command 键，按 Ctrl+C 退出...")
    listener = KeyboardListener(on_shortcut, "cmd_r")
    listener.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止监听")
