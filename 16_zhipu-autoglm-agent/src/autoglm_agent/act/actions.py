from __future__ import annotations

"""操作层：把“定位→点击→治理→稳定等待”封装成高容错原子动作。"""

import time
from typing import Callable, List, Optional

from ..config import Settings
from ..device.base import Device
from ..guard.popup import PopupGovernor
from ..locate.locator import FaultTolerantLocator, LocateError
from ..locate.spec import ElementSpec
from ..perception.screen import Screen, capture
from ..vision.base import OcrBackend


class Controller:
    def __init__(self, device: Device, settings: Settings, ocr: Optional[OcrBackend] = None):
        self.device = device
        self.settings = settings
        self.locator = FaultTolerantLocator(device, settings, ocr=ocr)
        self.popups = PopupGovernor(settings)
        self.ocr = ocr
        self.trace: List[dict] = []

    # ---- 感知 ----
    def snapshot(self) -> Screen:
        return capture(self.device, self.ocr)

    def refresh(self) -> None:
        self.popups.handle(self.device, self.ocr)

    # ---- 原子动作 ----
    def launch(self, target: str, settle: float = 0.4) -> None:
        self.device.launch(target)
        time.sleep(settle)
        self.popups.handle(self.device, self.ocr)
        self.trace.append({"action": "launch", "target": target})

    def click(self, spec: ElementSpec, timeout: Optional[float] = None,
              settle: float = 0.35) -> None:
        cand = self.locator.locate(spec, timeout=timeout)
        self.device.tap(*cand.center)
        self.trace.append({"action": "click", "spec": spec.name,
                           "source": cand.source, "conf": cand.conf,
                           "at": [round(v) for v in cand.center]})
        time.sleep(settle)
        self.popups.handle(self.device, self.ocr)

    def tap_if_present(self, spec: ElementSpec) -> bool:
        cand = self.locator.find(spec, screen=self.snapshot())
        if cand:
            self.device.tap(*cand.center)
            time.sleep(0.3)
            self.trace.append({"action": "tap_if", "spec": spec.name, "hit": True})
            return True
        self.trace.append({"action": "tap_if", "spec": spec.name, "hit": False})
        return False

    def type_text(self, spec: ElementSpec, text: str, clear: bool = True,
                  settle: float = 0.25) -> None:
        cand = self.locator.locate(spec)
        x, y = cand.center
        self.device.tap(x, y)
        time.sleep(0.2)
        if clear:
            self.device.clear_field()
        self.device.input_text(text)
        self.device.key("hide_keyboard")
        self.trace.append({"action": "type", "spec": spec.name, "text": text})
        time.sleep(settle)

    def wait_for(self, predicate: Callable[[Screen], bool], timeout: Optional[float] = None,
                 message: str = "页面条件") -> Screen:
        timeout = self.settings.locate_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            screen = self.snapshot()
            self.popups.handle(self.device, self.ocr)
            if predicate(screen):
                return screen
            if time.monotonic() >= deadline:
                raise LocateError(f"等待超时: {message}")
            time.sleep(self.settings.locate_poll_interval)

    def expect_texts(self, *needles: str, timeout: Optional[float] = None) -> Screen:
        return self.wait_for(lambda s: all(s.contains(n) for n in needles),
                             timeout=timeout, message="期望文本 " + "/".join(needles))

    def back(self) -> None:
        self.device.back()
        time.sleep(0.3)
        self.popups.handle(self.device, self.ocr)
