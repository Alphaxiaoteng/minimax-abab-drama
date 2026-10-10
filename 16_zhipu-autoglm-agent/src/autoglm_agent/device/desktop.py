from __future__ import annotations

import time
from typing import List, Optional, Tuple

from .base import Bounds, Device, UiElement


class DesktopDevice(Device):
    """桌面端（macOS/Windows/Linux）设备适配，基于 pyautogui。

    UI 树来自辅助 OCR（vision 层），此适配器的 ui_dump 返回空列表，
    定位引擎会自动降级到 OCR/模板/坐标先验策略。
    """

    name = "desktop"

    def __init__(self, failsafe: bool = True):
        import pyautogui  # 延迟导入：虚拟环境无需安装

        self._py = pyautogui
        self._py.FAILSAFE = failsafe

    def resolution(self) -> Tuple[int, int]:
        size = self._py.size()
        return int(size[0]), int(size[1])

    def ui_dump(self) -> List[UiElement]:
        return []

    def screenshot(self) -> Optional[bytes]:
        img = self._py.screenshot()
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def tap(self, x: float, y: float) -> None:
        self._py.click(int(x), int(y))

    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        self._py.moveTo(int(x), int(y))
        self._py.mouseDown()
        time.sleep(duration_ms / 1000.0)
        self._py.mouseUp()

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 400) -> None:
        self._py.moveTo(int(x1), int(y1))
        self._py.drag(int(x2), int(y2), duration=duration_ms / 1000.0)

    def input_text(self, text: str) -> None:
        self._py.typewrite(text, interval=0.01) if text.isascii() else self._py.write(text)

    def key(self, key_name: str) -> None:
        import sys

        if key_name == "back":
            self._py.press("escape")
        elif key_name == "select_all":
            mod = "command" if sys.platform == "darwin" else "ctrl"
            self._py.hotkey(mod, "a")
        elif key_name == "hide_keyboard":
            self._py.press("return")
        else:
            self._py.press(key_name)

    def clear_field(self) -> None:
        self.key("select_all")
        self._py.press("delete")

    def launch(self, target: str) -> None:
        import subprocess
        subprocess.run(["open", target], check=False)
