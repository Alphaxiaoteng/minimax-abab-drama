from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Bounds:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def intersects_viewport(self, width: float, height: float, min_visible: float = 0.3) -> bool:
        w = max(0.0, min(self.x2, width) - max(self.x1, 0.0))
        h = max(0.0, min(self.y2, height) - max(self.y1, 0.0))
        if w <= 0 or h <= 0:
            return False
        return (w * h) / max(self.area, 1e-6) >= min_visible


@dataclass
class UiElement:
    bounds: Bounds
    text: str = ""
    desc: str = ""
    rid: str = ""
    cls: str = ""
    clickable: bool = False
    scrollable: bool = False
    editable: bool = False
    extra: dict = field(default_factory=dict)

    def label(self) -> str:
        return self.text or self.desc or self.rid


class DeviceError(RuntimeError):
    """设备层不可用（无 adb / 无图形后端 / 命令超时）。上抛给流程层做降级。"""


class Device(ABC):
    """端侧设备统一操作接口（手机 / 桌面 / 虚拟）。"""

    name: str = "device"

    @abstractmethod
    def resolution(self) -> Tuple[int, int]:
        ...

    @abstractmethod
    def ui_dump(self) -> List[UiElement]:
        ...

    @abstractmethod
    def screenshot(self) -> Optional[bytes]:
        ...

    @abstractmethod
    def tap(self, x: float, y: float) -> None:
        ...

    @abstractmethod
    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        ...

    @abstractmethod
    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 400) -> None:
        ...

    @abstractmethod
    def input_text(self, text: str) -> None:
        ...

    @abstractmethod
    def key(self, key_name: str) -> None:
        ...

    @abstractmethod
    def launch(self, target: str) -> None:
        ...

    def type_into(self, x: float, y: float, text: str, clear: bool = True) -> None:
        self.tap(x, y)
        if clear:
            self.clear_field()
        self.input_text(text)

    def clear_field(self) -> None:
        self.key("select_all")
        self.key("delete")

    def scroll_down(self, amount: float = 0.6) -> None:
        w, h = self.resolution()
        cx = w / 2.0
        self.swipe(cx, h * (0.5 + amount / 2), cx, h * (0.5 - amount / 2))

    def scroll_up(self, amount: float = 0.6) -> None:
        w, h = self.resolution()
        cx = w / 2.0
        self.swipe(cx, h * (0.5 - amount / 2), cx, h * (0.5 + amount / 2))

    def back(self) -> None:
        self.key("back")

    def alive(self) -> bool:
        """设备是否仍可操作。真机适配器覆写；默认乐观返回 True。"""
        return True

    def app_hint(self) -> str:
        """当前前台应用标识，供自愈看门狗“重启应用”使用。"""
        return ""
