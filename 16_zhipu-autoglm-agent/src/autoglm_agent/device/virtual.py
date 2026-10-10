from __future__ import annotations

"""虚拟设备：用确定性状态机模拟 App/桌面应用，支撑离线联调、演示与单元测试。

真实硬件不可用时（评审环境/CI），同一套任务脚本可直接跑在本虚拟设备上，
UI 元素带可控漂移与 OCR 噪声，用于验证定位引擎的容错能力。
"""

import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .base import Bounds, Device, UiElement


@dataclass
class Effect:
    goto: Optional[str] = None
    popup: Optional[str] = None
    set: Dict[str, Any] = field(default_factory=dict)
    record: Optional[str] = None
    close_modal: bool = False
    set_challenge: Optional[str] = None
    goto_if: Optional[Tuple[str, str]] = None


@dataclass
class VElem:
    key: str
    x: float
    y: float
    w: float
    h: float
    text: str = ""
    desc: str = ""
    rid: str = ""
    cls: str = "Button"
    clickable: bool = True
    editable: bool = False
    scrollable: bool = False
    on_tap: Optional[Effect] = None
    noisy: bool = False


@dataclass
class ScreenDef:
    elements: List[VElem] = field(default_factory=list)
    content_height: float = 1.0
    modal: bool = False
    popup_on_enter: Optional[str] = None


@dataclass
class Scenario:
    screens: Dict[str, ScreenDef] = field(default_factory=dict)
    apps: Dict[str, str] = field(default_factory=dict)
    initial: str = "home"


class VirtualDevice(Device):
    name = "virtual"

    def __init__(self, scenario: Scenario, width: int = 1080, height: int = 2400,
                 seed: int = 7, drift_px: int = 0):
        self.scenario = scenario
        self._w, self._h = width, height
        self.rng = random.Random(seed)
        self.drift_px = drift_px
        self.screen = scenario.initial
        self.modal: Optional[str] = None
        self.offsets: Dict[str, float] = {}
        self.world: Dict[str, Any] = {"form": {}, "log": [], "vars": {}}
        self._focused: Optional[str] = None

    # ---- 状态访问 ----
    def resolution(self) -> Tuple[int, int]:
        return self._w, self._h

    @property
    def def_(self) -> ScreenDef:
        if self.modal:
            return self.scenario.screens[self.modal]
        return self.scenario.screens[self.screen]

    def _offset(self) -> float:
        return self.offsets.get(self.screen, 0.0)

    def _to_screen_px(self, el: VElem) -> Bounds:
        off = 0.0 if self.def_.modal else self._offset()
        y1 = (el.y - off) * self._h
        return Bounds(el.x * self._w, y1, (el.x + el.w) * self._w, y1 + el.h * self._h)

    def _jitter(self, b: Bounds) -> Bounds:
        if self.drift_px <= 0:
            return b
        j = lambda: self.rng.uniform(-self.drift_px, self.drift_px)
        return Bounds(b.x1 + j(), b.y1 + j(), b.x2 + j(), b.y2 + j())

    def visible_elements(self) -> List[Tuple[VElem, Bounds]]:
        out = []
        for el in self.def_.elements:
            b = self._to_screen_px(el)
            if b.intersects_viewport(self._w, self._h, min_visible=0.5 if not self.def_.modal else 0.9):
                out.append((el, self._jitter(b)))
        return out

    def _noisify(self, text: str) -> str:
        if not text:
            return text
        r = self.rng.random()
        if r < 0.25:
            return text + " "
        if r < 0.45 and len(text) > 1:
            i = self.rng.randrange(len(text))
            return text[:i] + " " + text[i:]
        return text

    # ---- 感知 ----
    def ui_dump(self) -> List[UiElement]:
        elems = []
        for el, b in self.visible_elements():
            text = el.text
            if el.noisy:
                text = self._noisify(text)
            elems.append(UiElement(
                bounds=b, text=text, desc=el.desc, rid=el.rid, cls=el.cls,
                clickable=el.clickable, scrollable=el.scrollable, editable=el.editable,
                extra={"key": el.key},
            ))
        return elems

    def screenshot(self) -> Optional[bytes]:
        payload = {
            "screen": self.modal or self.screen,
            "elements": [
                {"text": (self._noisify(el.text) if el.noisy else el.text),
                 "desc": el.desc, "bounds": list(el_b.center), "editable": el.editable}
                for el, el_b in self.visible_elements()
            ],
        }
        return json.dumps(payload).encode("utf-8")

    # ---- 操作 ----
    def _hit(self, x: float, y: float) -> Optional[VElem]:
        for el, b in reversed(self.visible_elements()):
            if b.x1 - 4 <= x <= b.x2 + 4 and b.y1 - 4 <= y <= b.y2 + 4:
                return el
        return None

    def tap(self, x: float, y: float) -> None:
        el = self._hit(x, y)
        if el is None:
            return
        self.world["log"].append({"tap": el.key, "screen": self.modal or self.screen})
        if el.editable:
            self._focused = el.key
            return
        self._apply(el.on_tap)

    def _apply(self, eff: Optional[Effect]) -> None:
        if eff is None:
            return
        if eff.close_modal:
            self.modal = None
        if eff.record:
            self.world["log"].append({"event": eff.record})
        for k, v in eff.set.items():
            self.world["vars"][k] = v
        if eff.set_challenge is not None:
            self.world["vars"]["challenge_code"] = eff.set_challenge
            self.world["log"].append({"event": "challenge", "code": eff.set_challenge})
        if eff.popup:
            if eff.popup in self.scenario.screens:
                self.modal = eff.popup
        if eff.goto and self._condition_ok(eff):
            self.screen = eff.goto
            nxt = self.scenario.screens[eff.goto]
            if nxt.popup_on_enter:
                self.modal = nxt.popup_on_enter

    def _condition_ok(self, eff: Effect) -> bool:
        """`goto_if=(变量名, 期望值)`：登录态等分流条件不满足时，入口点击不跳转。"""
        if eff.goto_if is None:
            return True
        key, expected = eff.goto_if
        return str(self.world["vars"].get(key, "")) == str(expected)

    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        self.tap(x, y)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 400) -> None:
        if self.def_.modal:
            return
        scr = self.def_
        dy = (y1 - y2) / self._h
        max_off = max(0.0, scr.content_height - 1.0)
        self.offsets[self.screen] = min(max(0.0, self._offset() + dy), max_off)

    def input_text(self, text: str) -> None:
        if self._focused:
            self.world["form"][self._focused] = self.world["form"].get(self._focused, "") + text
            self.world["vars"][self._focused] = self.world["form"][self._focused]

    def clear_field(self) -> None:
        if self._focused:
            self.world["form"][self._focused] = ""

    def key(self, key_name: str) -> None:
        if key_name == "back":
            if self.modal:
                self.modal = None
                return
            cur = self.scenario.screens.get(self.screen)
            back_eff = next((el.on_tap for el in cur.elements if el.key == "__back__"), None) if cur else None
            self._apply(back_eff) if back_eff else None
        elif key_name == "enter":
            self.world["log"].append({"key": "enter", "screen": self.modal or self.screen})
        elif key_name == "hide_keyboard":
            self._focused = None

    def launch(self, target: str) -> None:
        screen = self.scenario.apps.get(target, target)
        self.world["vars"]["app"] = target  # 自愈看门狗据此重启前台应用
        if screen in self.scenario.screens:
            self.screen = screen
            self.modal = None
            nxt = self.scenario.screens[screen]
            if nxt.popup_on_enter:
                self.modal = nxt.popup_on_enter
