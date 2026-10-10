from __future__ import annotations

"""桌面端设备适配（macOS/Windows/Linux）。

真机（pyautogui）与纯命令行环境（无图形后端）必须共用同一套接口：
无 pyautogui 时自动降级到 `NullDesktopBackend`，脚本不崩、只失去实际点击能力，
使「评审在无桌面环境跑通演示」与「真机复现」用同一份代码。
"""

import io
import subprocess
import sys
import time
from typing import List, Optional, Tuple

from .base import Bounds, Device, DeviceError, UiElement


class NullDesktopBackend:
    """无图形后端：所有操作记录日志并短路，截图返回 None。"""

    name = "null-desktop"

    def __init__(self, reason: str = ""):
        self.reason = reason or "未安装 pyautogui 或当前环境无图形后端"
        self._warned = False
        self.calls: List[str] = []

    def _note(self, action: str) -> None:
        self.calls.append(action)
        if not self._warned:
            print(f"[DesktopDevice] 降级为无效后端（{self.reason}）：操作 {action} 不会真正生效")
            self._warned = True

    def size(self) -> Tuple[int, int]:
        self._note("size")
        return (1920, 1080)

    def screenshot(self):
        self._note("screenshot")
        return None

    def click(self, x: int, y: int) -> None:
        self._note(f"click:{x},{y}")

    def moveTo(self, x: int, y: int) -> None:
        self._note(f"move:{x},{y}")

    def mouseDown(self) -> None:
        self._note("mouseDown")

    def mouseUp(self) -> None:
        self._note("mouseUp")

    def drag(self, x: int, y: int, duration: float = 0.4) -> None:
        self._note(f"drag:{x},{y}")

    def typewrite(self, text: str, interval: float = 0.01) -> None:
        self._note(f"type:{text[:12]}")

    def write(self, text: str) -> None:
        self._note(f"write:{text[:12]}")

    def press(self, key: str) -> None:
        self._note(f"press:{key}")

    def hotkey(self, *keys: str) -> None:
        self._note("hotkey:" + "+".join(keys))


def _load_pyautogui():
    try:
        import pyautogui  # 延迟导入：虚拟环境无需安装

        return pyautogui, ""
    except Exception as e:  # noqa: BLE001 —— 无图形后端属预期路径
        return None, f"{type(e).__name__}: {e}"


class DesktopDevice(Device):
    """桌面端设备：UI 树留给视觉层，定位引擎自动降级到 OCR/模板/坐标先验。"""

    name = "desktop"

    def __init__(self, failsafe: bool = True, scale_to: Optional[Tuple[int, int]] = None):
        py, err = _load_pyautogui()
        if py is None:
            self._py = NullDesktopBackend(err)
            self.degraded = True
        else:
            py.FAILSAFE = failsafe
            self._py = py
            self.degraded = False
        self._scale = scale_to

    # ---- 分辨率映射 ----
    def scale(self, width: int, height: int) -> None:
        """把逻辑分辨率映射到物理分辨率（分数缩放/远程桌面常见），保持宽高比。"""
        self._scale = (int(width), int(height))

    def _map(self, x: float, y: float) -> Tuple[int, int]:
        if not self._scale:
            return int(x), int(y)
        w, h = self.resolution()
        if w <= 0 or h <= 0:
            return int(x), int(y)
        return int(x * self._scale[0] / w), int(y * self._scale[1] / h)

    def alive(self) -> bool:
        return not self.degraded

    # ---- 感知 ----
    def resolution(self) -> Tuple[int, int]:
        size = self._py.size()
        return int(size[0]), int(size[1])

    def ui_dump(self) -> List[UiElement]:
        return []

    def screenshot(self) -> Optional[bytes]:
        img = self._py.screenshot()
        if img is None:
            return None
        buf = io.BytesIO()
        try:
            img.save(buf, format="PNG")
        except AttributeError:
            return None
        return buf.getvalue()

    # ---- 操作 ----
    def tap(self, x: float, y: float) -> None:
        px, py_ = self._map(x, y)
        self._py.click(px, py_)

    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        px, py_ = self._map(x, y)
        self._py.moveTo(px, py_)
        self._py.mouseDown()
        time.sleep(duration_ms / 1000.0)
        self._py.mouseUp()

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 400) -> None:
        ax, ay = self._map(x1, y1)
        bx, by = self._map(x2, y2)
        self._py.moveTo(ax, ay)
        self._py.drag(bx, by, duration=duration_ms / 1000.0)

    def input_text(self, text: str) -> None:
        if text.isascii():
            self._py.typewrite(text, interval=0.01)
        else:
            self._py.write(text)

    def key(self, key_name: str) -> None:
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
        if self.degraded:
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-a", target], check=False, timeout=15)
            elif sys.platform.startswith("win"):
                subprocess.run(["cmd", "/c", "start", "", target], check=False, timeout=15)
            else:
                subprocess.run([target], check=False, timeout=15)
        except (subprocess.SubprocessError, OSError) as e:
            raise DeviceError(f"桌面端启动应用失败 {target}：{e}") from e
