from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from .base import Bounds, Device, UiElement

_KEYMAP = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL",
    "select_all": None,
    "hide_keyboard": "KEYCODE_ESCAPE",
}


class AdbDevice(Device):
    """通过 adb 驱动的 Android 端侧设备（uiautomator dump 提供 UI 树）。"""

    name = "adb"

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self._cache: Optional[Tuple[int, int]] = None

    def _adb(self, *args: str, binary: bool = False) -> bytes:
        cmd = ["adb"] + (["-s", self.serial] if self.serial else []) + list(args)
        proc = subprocess.run(cmd, capture_output=True, check=True)
        return proc.stdout if binary else proc.stdout

    def resolution(self) -> Tuple[int, int]:
        if self._cache:
            return self._cache
        out = self._adb("shell", "wm", "size").decode()
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"无法解析屏幕分辨率: {out!r}")
        self._cache = (int(m.group(1)), int(m.group(2)))
        return self._cache

    def ui_dump(self) -> List[UiElement]:
        self._adb("shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
        raw = self._adb("shell", "cat", "/sdcard/window_dump.xml", binary=True).decode("utf-8", "ignore")
        return self._parse(raw)

    @staticmethod
    def _parse(xml: str) -> List[UiElement]:
        if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
            raise ValueError("uiautomator dump 含非法 DTD/实体声明，拒绝解析")
        root = ET.fromstring(xml)
        elems: List[UiElement] = []
        for node in root.iter("node"):
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if not m:
                continue
            x1, y1, x2, y2 = map(int, m.groups())
            if x2 <= x1 or y2 <= y1:
                continue
            cls = node.get("class", "")
            elems.append(UiElement(
                bounds=Bounds(x1, y1, x2, y2),
                text=node.get("text", ""),
                desc=node.get("content-desc", ""),
                rid=node.get("resource-id", ""),
                cls=cls,
                clickable=node.get("clickable") == "true",
                scrollable=node.get("scrollable") == "true",
                editable=cls.endswith(("EditText", "AutoCompleteTextView")),
            ))
        return elems

    def screenshot(self) -> Optional[bytes]:
        try:
            return self._adb("exec-out", "screencap", "-p", binary=True)
        except subprocess.SubprocessError:
            return None

    def tap(self, x: float, y: float) -> None:
        self._adb("shell", "input", "tap", str(int(x)), str(int(y)))

    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        p = str(int(x)) + " " + str(int(y))
        self._adb("shell", "input", "swipe", p, p, str(duration_ms))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 400) -> None:
        self._adb("shell", "input", "swipe",
                  str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration_ms))

    def input_text(self, text: str) -> None:
        escaped = text.replace(" ", "%s").replace("&", "\\&")
        self._adb("shell", "input", "text", escaped)

    def key(self, key_name: str) -> None:
        if key_name == "select_all":
            self._adb("shell", "input", "keyevent", "KEYCODE_MOVE_END")
            for _ in range(30):
                self._adb("shell", "input", "keyevent", "KEYCODE_DEL")
            return
        code = _KEYMAP.get(key_name)
        if code:
            self._adb("shell", "input", "keyevent", code)

    def launch(self, target: str) -> None:
        if ":" in target:
            pkg, activity = target.split(":", 1)
            self._adb("shell", "am", "start", "-n", f"{pkg}/{activity}")
        else:
            self._adb("shell", "monkey", "-p", target, "-c",
                      "android.intent.category.LAUNCHER", "1")
        time.sleep(1.5)
