from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from .base import Bounds, Device, DeviceError, UiElement

_KEYMAP = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL",
    "select_all": None,
    "hide_keyboard": "KEYCODE_ESCAPE",
}


class AdbDevice(Device):
    """通过 adb 驱动的 Android 端侧设备（uiautomator dump 提供 UI 树）。

    真机环境不保证任意命令都成功（未连接/离线/权限不足/attached 多设备），
    因此每次调用都带超时与异常归一化：失败统一抛 `DeviceError`，
    由流程层决定重连、切换设备还是降级到其他设备适配器。
    """

    name = "adb"
    default_timeout = 15.0
    fallback_resolution = (1080, 2400)

    def __init__(self, serial: Optional[str] = None, timeout: Optional[float] = None):
        self.serial = serial
        self.timeout = timeout or self.default_timeout
        self._cache: Optional[Tuple[int, int]] = None

    @property
    def app_hint(self) -> str:
        try:
            out = self._adb("shell", "dumpsys", "window", "windows", binary=True)
        except DeviceError:
            return ""
        m = re.search(r"mCurrentFocus=.*?([\w.]+)/", out.decode("utf-8", "ignore"))
        return m.group(1) if m else ""

    def _adb(self, *args: str, binary: bool = False) -> bytes:
        cmd = ["adb"] + (["-s", self.serial] if self.serial else []) + list(args)
        try:
            proc = subprocess.run(cmd, capture_output=True, check=True, timeout=self.timeout)
        except FileNotFoundError as e:
            raise DeviceError("未找到 adb 可执行文件：请安装 platform-tools 并在 PATH 中可用") from e
        except subprocess.TimeoutExpired as e:
            raise DeviceError(f"adb 命令超时（{self.timeout:.0f}s）：{' '.join(args[:3])}") from e
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or b"").decode("utf-8", "ignore").strip()
            raise DeviceError(f"adb 命令失败（{e.returncode}）：{' '.join(args[:3])} {detail}") from e
        return proc.stdout if binary else proc.stdout

    # ---- 连接 ----
    def alive(self) -> bool:
        try:
            self._adb("shell", "echo", "ok", binary=True)
            return True
        except DeviceError:
            return False

    def wait_boot(self, timeout: float = 60.0) -> bool:
        """等待设备就绪：先 wait-for-device，再轮询 sys.boot_completed。"""
        try:
            self._adb("wait-for-device", binary=True)
        except DeviceError:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                out = self._adb("shell", "getprop", "sys.boot_completed", binary=True)
                if out.decode("utf-8", "ignore").strip() == "1":
                    return True
            except DeviceError:
                return False
            time.sleep(1.0)
        return False

    def resolution(self) -> Tuple[int, int]:
        if self._cache:
            return self._cache
        out = ""
        try:
            out = self._adb("shell", "wm", "size").decode("utf-8", "ignore")
        except DeviceError:
            out = ""
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            w, h = self.fallback_resolution
            print(f"[AdbDevice] 无法解析屏幕分辨率（{out.strip() or '命令失败'}），回退 {w}x{h}")
            self._cache = self.fallback_resolution
            return self._cache
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
                continue  # 单节点结构异常不应让整屏丢失
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
                extra={"enabled": node.get("enabled", "true"),
                       "focusable": node.get("focusable", "false")},
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
