from __future__ import annotations

"""操作层：把「体检 → 定位 → 视觉自校验 → 执行 → 回读验证 → 弹窗治理」封装成高容错原子动作。

三层防护，缺一不可：
1. **动作前体检**（`watch`）：黑屏/冻屏/弹窗挡住的帧不参与定位决策；
2. **视觉自校验**（`_confirm_target`）：定位到点击之间存在时间窗，重定位确认目标没漂；
3. **执行后回读**（`type_text` 的框内文本校验）：输入类动作最怕“静默失败”。
"""

import time
from typing import Callable, List, Optional, Tuple

from ..config import Settings
from ..device.base import Device
from ..guard.popup import PopupGovernor
from ..guard.watchdog import Issue, Watchdog
from ..locate.locator import FaultTolerantLocator, LocateError
from ..locate.spec import ElementSpec
from ..locate.strategy import Candidate
from ..perception.screen import Screen, capture
from ..vision.base import OcrBackend, TemplateBackend

_DRIFT_PX = 12.0
_SHAPE_TOL = 0.4


class Controller:
    def __init__(self, device: Device, settings: Settings, ocr: Optional[OcrBackend] = None,
                 templates: Optional[TemplateBackend] = None):
        self.device = device
        self.settings = settings
        self.locator = FaultTolerantLocator(device, settings, ocr=ocr, templates=templates)
        self.popups = PopupGovernor(settings)
        self.ocr = ocr
        self.templates = templates
        self.watchdog = Watchdog(device, settings, ocr=ocr, popups=self.popups,
                                 launch=self.launch)
        self.trace: List[dict] = []
        self.issues: List[Issue] = []

    # ---- 感知 ----
    def snapshot(self) -> Screen:
        return capture(self.device, self.ocr, self.templates)

    def refresh(self) -> None:
        self.popups.handle(self.device, self.ocr)

    def watch(self) -> List[Issue]:
        """动作前体检 + 自愈处置。返回本轮发现并处置过的故障。"""
        found = self.watchdog.check()
        for issue in found:
            self.issues.append(issue)
            self.trace.append({"action": "watch", "kind": issue.kind,
                               "severity": issue.severity, "handled": issue.action})
        return found

    # ---- 定位后自校验 ----
    @staticmethod
    def _same_target(a: Candidate, b: Candidate) -> bool:
        if a.element_key and a.element_key == b.element_key:
            return True
        dx = abs(a.center[0] - b.center[0])
        dy = abs(a.center[1] - b.center[1])
        if dx > _DRIFT_PX or dy > _DRIFT_PX:
            return False
        aw, ah = a.shape
        bw, bh = b.shape
        if aw > 0 and bw > 0 and abs(aw - bw) / max(aw, bw) > _SHAPE_TOL:
            return False
        if ah > 0 and bh > 0 and abs(ah - bh) / max(ah, bh) > _SHAPE_TOL:
            return False
        return True

    def _confirm_target(self, spec: ElementSpec, cand: Candidate,
                        attempts: Optional[int] = None) -> Candidate:
        """点击前重采样确认目标仍在原处；漂移则重新定位。校验轮数可配（0 = 关闭）。"""
        rounds = self.settings.action_max_verify if attempts is None else attempts
        if rounds <= 0:
            return cand
        current = cand
        for idx in range(rounds):
            again = self.locator.find(spec, screen=self.snapshot())
            if again is not None and self._same_target(current, again):
                return again
            self.trace.append({"action": "plan_drift", "spec": spec.name, "round": idx + 1,
                               "expected": [round(v) for v in current.center],
                               "actual": [round(v) for v in again.center] if again else None})
            if again is not None:
                current = again  # 目标漂移到新位置：接受新位置并再确认一轮
        return current

    # ---- 原子动作 ----
    def launch(self, target: str, settle: float = 0.4) -> None:
        self.device.launch(target)
        time.sleep(settle)
        self.popups.handle(self.device, self.ocr)
        self.trace.append({"action": "launch", "target": target})

    def click(self, spec: ElementSpec, timeout: Optional[float] = None,
              settle: float = 0.35) -> None:
        self.watch()
        cand = self.locator.locate(spec, timeout=timeout)
        cand = self._confirm_target(spec, cand)
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

    # ---- 输入 ----
    def _field_text(self, spec: ElementSpec, cand: Optional[Candidate] = None,
                    screen: Optional[Screen] = None) -> str:
        """回读输入框当前内容。

        解析顺序：① 候选元素 key（虚拟设备/真机 uiautomator 都能给出稳定身份）
        → ② 规范名模糊匹配（兼容既有虚拟场景的 `app_xxx` 命名）
        → ③ 当前焦点元素 → ④ 屏幕文本兜底（真机无世界状态时用屏幕是否含期望值判断）。
        """
        world = getattr(self.device, "world", None)
        if isinstance(world, dict):
            form = dict(world.get("form", {}))
            vars_ = world.get("vars", {})
            if cand is not None and cand.element_key:
                key = cand.element_key
                for source in (form, vars_):
                    if key in source:
                        return str(source[key])
            target = spec.name
            for source in (form, vars_):
                for k, v in source.items():
                    if target and (target in k or k.endswith(target)):
                        return str(v)
            focused = getattr(self.device, "_focused", None)
            if focused:
                return str(form.get(focused, vars_.get(focused, "")))
        return ""

    def type_text(self, spec: ElementSpec, text: str, clear: bool = True,
                  settle: float = 0.25) -> None:
        self.watch()
        cand = self.locator.locate(spec)
        cand = self._confirm_target(spec, cand)
        rounds = max(1, self.settings.action_max_verify)
        last_seen = ""
        for attempt in range(1, rounds + 1):
            x, y = cand.center
            self.device.tap(x, y)
            time.sleep(0.2)
            if clear:
                self.device.clear_field()
            self.device.input_text(text)
            self.device.key("hide_keyboard")
            last_seen = self._field_text(spec)
            if not last_seen or last_seen.strip() == text.strip():
                self.trace.append({"action": "type", "spec": spec.name, "text": text,
                                   "attempt": attempt, "readback": bool(last_seen)})
                time.sleep(settle)
                return
            self.trace.append({"action": "type_retry", "spec": spec.name,
                               "attempt": attempt, "got": last_seen})
            re_located = self.locator.find(spec, screen=self.snapshot())
            if re_located is not None:
                cand = re_located
            time.sleep(self.settings.retry_backoff_base)
        raise LocateError(f"输入校验失败 [{spec.name}]：{rounds} 次键入后框内为「{last_seen}」，期望「{text}」")

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
