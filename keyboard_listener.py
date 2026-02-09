"""
键盘监听模块 - 监听可配置的快捷键（支持组合键）
"""
import sys
import time
import threading
from pynput import keyboard
from typing import Callable, Optional, Tuple, Set, List


# 双击检测间隔（秒）
DOUBLE_CLICK_INTERVAL = 0.4

# 平台检测
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# 快捷键映射 - 基础映射（跨平台）
SHORTCUT_KEY_MAP = {
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "ctrl": keyboard.Key.ctrl_l,  # 通用 ctrl，不区分左右
    "alt_r": keyboard.Key.alt_r,
    "alt_l": keyboard.Key.alt_l,
    "alt": keyboard.Key.alt_l,  # 通用 alt
    "shift_r": keyboard.Key.shift_r,
    "shift_l": keyboard.Key.shift_l,
    "shift": keyboard.Key.shift_l,  # 通用 shift
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
}

# macOS 专用键
if IS_MACOS:
    SHORTCUT_KEY_MAP.update({
        "cmd_r": keyboard.Key.cmd_r,
        "cmd_l": keyboard.Key.cmd_l,
        "cmd": keyboard.Key.cmd_l,  # 通用 cmd
        "fn": keyboard.Key.f20,
    })

# Windows 专用键
if IS_WINDOWS:
    SHORTCUT_KEY_MAP.update({
        "win_r": keyboard.Key.cmd_r,  # Windows 键映射
        "win_l": keyboard.Key.cmd_l,
        "win": keyboard.Key.cmd_l,  # 通用 win
    })

# 反向映射：Key -> 标识符
KEY_TO_NAME = {v: k for k, v in SHORTCUT_KEY_MAP.items()}

# 修饰键集合（用于判断是否是修饰键）
MODIFIER_KEYS = {
    "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r",
    "shift", "shift_l", "shift_r",
    "cmd", "cmd_l", "cmd_r",
    "win", "win_l", "win_r",
}

# 修饰键规范化映射（将左右区分的修饰键映射到通用名）
MODIFIER_NORMALIZE = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt",
    "shift_l": "shift", "shift_r": "shift",
    "cmd_l": "cmd", "cmd_r": "cmd",
    "win_l": "win", "win_r": "win",
}

# 显示名称映射
KEY_DISPLAY_NAMES = {
    "cmd_r": "Right Command",
    "cmd_l": "Left Command",
    "cmd": "Command",
    "ctrl_r": "Right Control",
    "ctrl_l": "Left Control",
    "ctrl": "Control",
    "alt_r": "Right Alt/Option",
    "alt_l": "Left Alt/Option",
    "alt": "Alt/Option",
    "shift_r": "Right Shift",
    "shift_l": "Left Shift",
    "shift": "Shift",
    "caps_lock": "Caps Lock",
    "space": "Space",
    "tab": "Tab",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
    "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
    "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "fn": "Fn",
    "win_r": "Right Windows",
    "win_l": "Left Windows",
    "win": "Windows",
}


def parse_shortcut(shortcut_str: str) -> Tuple[Set[str], Optional[str]]:
    """
    解析快捷键字符串，返回 (修饰键集合, 主键)

    格式示例:
    - "ctrl+shift+a" -> ({"ctrl", "shift"}, "a")
    - "cmd+space" -> ({"cmd"}, "space")
    - "f12" -> (set(), "f12")
    - "cmd_r" -> (set(), "cmd_r")  向后兼容单键

    Args:
        shortcut_str: 快捷键字符串

    Returns:
        (修饰键集合, 主键) 元组
    """
    if not shortcut_str:
        return set(), None

    shortcut_str = shortcut_str.lower().strip()

    # 检查是否是组合键格式（包含 +）
    if '+' in shortcut_str:
        parts = [p.strip() for p in shortcut_str.split('+')]
        modifiers = set()
        main_key = None

        for part in parts:
            if part in MODIFIER_KEYS:
                # 规范化修饰键（ctrl_l -> ctrl）
                normalized = MODIFIER_NORMALIZE.get(part, part)
                modifiers.add(normalized)
            else:
                # 最后一个非修饰键是主键
                main_key = part

        return modifiers, main_key
    else:
        # 单键格式（向后兼容）
        # 检查是否是修饰键（如 cmd_r），如果是则作为主键处理
        return set(), shortcut_str


def format_shortcut(modifiers: Set[str], main_key: Optional[str]) -> str:
    """
    将修饰键集合和主键格式化为快捷键字符串

    Args:
        modifiers: 修饰键集合
        main_key: 主键

    Returns:
        快捷键字符串，如 "ctrl+shift+a"
    """
    parts = []

    # 按固定顺序添加修饰键
    for mod in ["ctrl", "alt", "shift", "cmd", "win"]:
        if mod in modifiers:
            parts.append(mod)

    if main_key:
        parts.append(main_key)

    return "+".join(parts) if parts else ""


def get_shortcut_display(shortcut_str: str) -> str:
    """
    获取快捷键的显示名称

    Args:
        shortcut_str: 快捷键字符串

    Returns:
        显示名称，如 "Control + Shift + A"
    """
    modifiers, main_key = parse_shortcut(shortcut_str)

    if not modifiers and main_key:
        # 单键情况
        return KEY_DISPLAY_NAMES.get(main_key, main_key.upper())

    parts = []
    for mod in ["ctrl", "alt", "shift", "cmd", "win"]:
        if mod in modifiers:
            parts.append(KEY_DISPLAY_NAMES.get(mod, mod.title()))

    if main_key:
        parts.append(KEY_DISPLAY_NAMES.get(main_key, main_key.upper()))

    return " + ".join(parts)


def get_default_shortcut() -> Tuple[str, str]:
    """获取当前平台的默认快捷键"""
    if IS_MACOS:
        return ("cmd_r", "Right Command")
    elif IS_WINDOWS:
        return ("ctrl_r", "Right Control")
    else:
        return ("ctrl_r", "Right Control")


def _normalize_key(key) -> Optional[str]:
    """
    将 pynput 的 key 对象规范化为字符串标识

    Args:
        key: pynput 的 Key 对象或 KeyCode

    Returns:
        规范化的键标识符，如 "ctrl", "a", "f1" 等
    """
    # 特殊键
    if key in KEY_TO_NAME:
        name = KEY_TO_NAME[key]
        # 规范化修饰键
        return MODIFIER_NORMALIZE.get(name, name)

    # 普通字符键
    if hasattr(key, 'char') and key.char:
        return key.char.lower()

    # 通过 vk 或 name 属性获取
    if hasattr(key, 'name'):
        return key.name.lower()

    return None


def _is_modifier_key(key) -> bool:
    """判断是否是修饰键"""
    key_name = _normalize_key(key)
    if key_name:
        return key_name in MODIFIER_KEYS or MODIFIER_NORMALIZE.get(key_name) in MODIFIER_KEYS
    return False


class KeyboardListener:
    """监听可配置的快捷键（支持组合键）"""

    # 时间阈值（秒）
    MIN_PRESS_TIME = 0.05   # 最短按下时间 50ms，避免误触
    MAX_PRESS_TIME = 1.5    # 最长按下时间 1.5s，避免正常按压被误判为长按

    def __init__(self, callback: Callable, shortcut_key: str = "cmd_r",
                 double_click_callback: Callable = None,
                 should_handle_double_click: Optional[Callable[[], bool]] = None):
        """
        Args:
            callback: 快捷键触发时的回调函数
            shortcut_key: 快捷键标识（如 "cmd_r", "ctrl+shift+a" 等）
            double_click_callback: 双击快捷键时的回调函数
            should_handle_double_click: 是否允许处理双击的判断函数
        """
        self.callback = callback
        self.double_click_callback = double_click_callback
        self.should_handle_double_click = should_handle_double_click
        self.listener = None

        # 当前监听的快捷键配置
        self._shortcut_str = shortcut_key
        self._required_modifiers: Set[str] = set()  # 需要的修饰键
        self._main_key: Optional[str] = None  # 主键
        self._is_single_key_mode = False  # 是否是单键模式（向后兼容）

        # 解析快捷键
        self._parse_and_set_shortcut(shortcut_key)

        # 状态跟踪
        self._pressed_modifiers: Set[str] = set()  # 当前按下的修饰键
        self._main_key_pressed = False  # 主键是否按下
        self._main_key_press_time = 0  # 主键按下时间
        self._other_key_pressed = False  # 是否按下了其他键
        self._last_release_time = 0  # 上一次释放时间，用于双击检测
        self._pending_single_click = None  # 待执行的单击定时器
        self._lock = threading.Lock()

    def _parse_and_set_shortcut(self, shortcut_str: str):
        """解析并设置快捷键"""
        modifiers, main_key = parse_shortcut(shortcut_str)

        if not modifiers and main_key:
            # 单键模式（如 cmd_r, f12）
            self._is_single_key_mode = True
            self._required_modifiers = set()
            self._main_key = main_key
        else:
            # 组合键模式
            self._is_single_key_mode = False
            self._required_modifiers = modifiers
            self._main_key = main_key

    def set_shortcut(self, shortcut_key: str):
        """更新快捷键"""
        with self._lock:
            self._shortcut_str = shortcut_key
            self._parse_and_set_shortcut(shortcut_key)
            # 重置状态
            self._pressed_modifiers.clear()
            self._main_key_pressed = False
            self._main_key_press_time = 0
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

    def _check_shortcut_match(self) -> bool:
        """
        检查当前按下的键是否匹配快捷键配置

        Returns:
            True 如果匹配，False 否则
        """
        if self._is_single_key_mode:
            # 单键模式：只需要主键按下
            # 如果主键本身是修饰键（如 cmd_r），允许对应的规范化修饰键存在
            if not self._main_key_pressed:
                return False

            # 检查是否有额外的修饰键
            main_key_normalized = MODIFIER_NORMALIZE.get(self._main_key)
            if main_key_normalized:
                # 主键是修饰键，允许它的规范化版本存在
                extra_modifiers = self._pressed_modifiers - {main_key_normalized}
                return len(extra_modifiers) == 0
            else:
                # 主键不是修饰键，不能有任何修饰键
                return len(self._pressed_modifiers) == 0
        else:
            # 组合键模式：需要所有要求的修饰键 + 主键
            return (self._main_key_pressed and
                    self._required_modifiers == self._pressed_modifiers)

    def _on_press(self, key):
        """按键按下事件"""
        # 获取原始键名（不规范化）
        raw_key_name = None
        if key in KEY_TO_NAME:
            raw_key_name = KEY_TO_NAME[key]
        elif hasattr(key, 'char') and key.char:
            raw_key_name = key.char.lower()
        elif hasattr(key, 'name'):
            raw_key_name = key.name.lower()

        if not raw_key_name:
            return

        # 规范化后的键名
        normalized_key_name = MODIFIER_NORMALIZE.get(raw_key_name, raw_key_name)

        with self._lock:
            # 判断是否是修饰键
            if raw_key_name in MODIFIER_KEYS or normalized_key_name in MODIFIER_KEYS:
                self._pressed_modifiers.add(normalized_key_name)

                # 单键模式下，修饰键本身也可能是主键
                # 需要检查原始键名是否匹配（如 cmd_r）
                if self._is_single_key_mode and raw_key_name == self._main_key:
                    if not self._main_key_pressed:
                        self._main_key_pressed = True
                        self._main_key_press_time = time.time()
                        self._other_key_pressed = False
            else:
                # 非修饰键
                if raw_key_name == self._main_key or normalized_key_name == self._main_key:
                    if not self._main_key_pressed:
                        self._main_key_pressed = True
                        self._main_key_press_time = time.time()
                        self._other_key_pressed = False
                else:
                    # 其他键被按下
                    if self._main_key_pressed:
                        self._other_key_pressed = True

    def _on_release(self, key):
        """按键释放事件"""
        # 获取原始键名（不规范化）
        raw_key_name = None
        if key in KEY_TO_NAME:
            raw_key_name = KEY_TO_NAME[key]
        elif hasattr(key, 'char') and key.char:
            raw_key_name = key.char.lower()
        elif hasattr(key, 'name'):
            raw_key_name = key.name.lower()

        if not raw_key_name:
            return

        # 规范化后的键名
        normalized_key_name = MODIFIER_NORMALIZE.get(raw_key_name, raw_key_name)

        with self._lock:
            # 检查是否释放的是主键
            is_main_key_release = (raw_key_name == self._main_key or
                                   normalized_key_name == self._main_key)

            if is_main_key_release and self._main_key_pressed:
                press_duration = time.time() - self._main_key_press_time

                # 检查是否为有效触发
                shortcut_matched = self._check_shortcut_match()

                if (shortcut_matched and
                    not self._other_key_pressed and
                    self.MIN_PRESS_TIME <= press_duration <= self.MAX_PRESS_TIME):

                    current_time = time.time()

                    allow_double_click = self.double_click_callback is not None
                    if allow_double_click and self.should_handle_double_click:
                        try:
                            allow_double_click = bool(self.should_handle_double_click())
                        except Exception:
                            allow_double_click = False

                    # 仅当存在待执行单击时，才将当前点击识别为双击
                    is_double_click = (
                        allow_double_click and
                        self._pending_single_click is not None and
                        current_time - self._last_release_time <= DOUBLE_CLICK_INTERVAL
                    )

                    if is_double_click:
                        # 双击检测：取消待执行的单击，执行双击回调
                        if self._pending_single_click:
                            self._pending_single_click.cancel()
                            self._pending_single_click = None
                        self._last_release_time = 0  # 重置，避免三击
                        threading.Thread(target=self.double_click_callback, daemon=True).start()
                    else:
                        if self._pending_single_click:
                            self._pending_single_click.cancel()
                            self._pending_single_click = None

                        if allow_double_click:
                            # 可能是单击：延迟执行，等待看是否有双击
                            self._last_release_time = current_time
                            self._pending_single_click = threading.Timer(
                                DOUBLE_CLICK_INTERVAL,
                                self._execute_single_click
                            )
                            self._pending_single_click.start()
                        else:
                            # 当前状态不需要双击，直接执行单击回调
                            self._last_release_time = 0
                            self._trigger_single_click()

                # 重置主键状态
                self._main_key_pressed = False
                self._main_key_press_time = 0
                self._other_key_pressed = False

            # 更新修饰键状态
            if raw_key_name in MODIFIER_KEYS or normalized_key_name in MODIFIER_KEYS:
                self._pressed_modifiers.discard(normalized_key_name)

    def _execute_single_click(self):
        """执行单击回调"""
        with self._lock:
            self._pending_single_click = None
            self._last_release_time = 0
        self._trigger_single_click()

    def _trigger_single_click(self):
        """异步触发单击回调"""
        threading.Thread(target=self.callback, daemon=True).start()


# 保留旧的类名作为别名，保持向后兼容
RightCommandListener = KeyboardListener


class ShortcutRecorder:
    """快捷键录制器 - 用于用户自定义快捷键"""

    # 录制超时时间（秒）
    RECORD_TIMEOUT = 10

    def __init__(self, on_recorded: Callable[[str, str], None] = None,
                 on_timeout: Callable = None,
                 on_cancel: Callable = None):
        """
        初始化快捷键录制器

        Args:
            on_recorded: 录制成功回调，参数为 (key_id, display_name)
            on_timeout: 超时回调
            on_cancel: 取消回调（按 Escape）
        """
        self.on_recorded = on_recorded
        self.on_timeout = on_timeout
        self.on_cancel = on_cancel
        self._listener: Optional[keyboard.Listener] = None
        self._recording = False
        self._timeout_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def start(self):
        """开始录制"""
        with self._lock:
            if self._recording:
                return
            self._recording = True

        # 启动超时计时器
        self._timeout_timer = threading.Timer(self.RECORD_TIMEOUT, self._on_timeout)
        self._timeout_timer.start()

        # 启动键盘监听
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()

    def stop(self):
        """停止录制"""
        with self._lock:
            if not self._recording:
                return
            self._recording = False

        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None

        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_timeout(self):
        """超时处理"""
        self.stop()
        if self.on_timeout:
            threading.Thread(target=self.on_timeout, daemon=True).start()

    def _on_press(self, key):
        """按键按下事件"""
        pass  # 我们只关心释放事件

    def _on_release(self, key):
        """按键释放事件"""
        with self._lock:
            if not self._recording:
                return

        # 检查是否是 Escape 键（取消）
        if key == keyboard.Key.esc:
            self.stop()
            if self.on_cancel:
                threading.Thread(target=self.on_cancel, daemon=True).start()
            return

        # 检查是否是支持的快捷键
        key_id = KEY_TO_NAME.get(key)
        if key_id:
            display_name = KEY_DISPLAY_NAMES.get(key_id, key_id)
            self.stop()
            if self.on_recorded:
                threading.Thread(
                    target=self.on_recorded,
                    args=(key_id, display_name),
                    daemon=True
                ).start()


def get_available_shortcuts() -> list:
    """获取当前平台可用的快捷键列表"""
    result = []
    for key_id in SHORTCUT_KEY_MAP.keys():
        display = KEY_DISPLAY_NAMES.get(key_id, key_id)
        result.append({"key": key_id, "display": display})
    return result


if __name__ == "__main__":
    # 测试代码
    import sys

    def on_shortcut():
        print("快捷键被触发！")

    # 支持命令行参数指定快捷键
    if len(sys.argv) > 1:
        shortcut = sys.argv[1]
        display = get_shortcut_display(shortcut)
    else:
        shortcut, display = get_default_shortcut()

    print(f"快捷键: {display} ({shortcut})")
    print(f"开始监听，按 Ctrl+C 退出...")

    # 解析并显示快捷键结构
    modifiers, main_key = parse_shortcut(shortcut)
    print(f"  修饰键: {modifiers}")
    print(f"  主键: {main_key}")

    listener = KeyboardListener(on_shortcut, shortcut)
    listener.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
        print("\n已停止监听")
