from __future__ import annotations

"""屏幕健康度感知：把“这一帧能不能信”变成可度量、可解释、可处置的信号。

端侧自动化的真正杀手不是单步定位失败，而是**静默的坏帧**：
黑屏/白屏（应用未渲染完）、画面冻结（上一帧残留、后台 ANR）、弹窗拦截（点击被吃掉）。
三者都会让后续所有步骤在错误的前提下执行，最终表现为“跑完了但结果错”。
本模块在每步动作前给出 `HealthReport`，由 `guard/watchdog.py` 决定处置动作。
"""

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from ..device.base import Device
from ..vision.base import OcrBackend
from .screen import Screen, capture, normalize_text

if TYPE_CHECKING:  # 仅供类型标注：运行时导入会与 locate/guard 形成循环依赖
    from ..guard.popup import PopupGovernor

_BLANK_MAX_TEXTS = 1
_THIN_ELEMENTS = 3
_THIN_TEXTS = 2


@dataclass
class HealthReport:
    """一帧的体检结论。所有扣分项都带中文原因，便于日志与录屏讲解。"""

    screen_sig: str
    text_sig: str
    element_count: int
    text_count: int
    blank: bool = False
    frozen: bool = False
    popup_pending: bool = False
    popup_title: str = ""
    health: float = 1.0
    reasons: List[str] = field(default_factory=list)


def _texts(screen: Screen) -> List[str]:
    out = [normalize_text(e.label()) for e in screen.elements if e.label()]
    out += [normalize_text(h.text) for h in screen.ocr_hits]
    return [t for t in out if t]


def _popup_probe(screen: Screen):
    """弹窗检测沿用 guard 的判定逻辑，但**延迟导入**：
    guard.popup 依赖 locate.strategy，而 locate 又依赖本模块，
    在模块级导入会形成环。运行时导入既避免环，也保持判定单一实现。"""
    from ..guard.popup import PopupGovernor

    return PopupGovernor().find_pending(screen)


def frame_signatures(screen: Screen) -> Tuple[str, str]:
    """返回 (屏幕签名, 文本签名)。

    屏幕签名含坐标：能识别“同内容换位置”的重绘。
    文本签名只含文本：抗像素级漂移，用于判断“页面到底变没变”。
    """
    ui_texts = [normalize_text(e.label()) for e in screen.elements if e.label()]
    ui_texts = [t for t in ui_texts if t]
    ocr_texts = [normalize_text(h.text) for h in screen.ocr_hits]
    ocr_texts = [t for t in ocr_texts if t]
    text_sig = hashlib.sha1(
        "\u0001".join(sorted(ui_texts + ocr_texts)).encode("utf-8")).hexdigest()[:12]
    structured = []
    for e in screen.elements:
        cx, cy = e.bounds.center
        structured.append(f"{normalize_text(e.label())}@{round(cx)},{round(cy)}")
    structured += [f"ocr:{t}" for t in ocr_texts]
    screen_sig = hashlib.sha1(
        "\u0001".join(sorted(structured)).encode("utf-8")).hexdigest()[:12]
    return screen_sig, text_sig


class HealthProbe:
    """逐帧体检器：内部只保留上一帧签名，零图像缓存，开销为一次 UI 树/OCR 抓取。"""

    def __init__(self, device: Device, ocr: Optional[OcrBackend] = None,
                 popups: Optional["PopupGovernor"] = None):
        self.device = device
        self.ocr = ocr
        self._popups = popups
        self._prev_screen_sig: Optional[str] = None
        self._prev_text_sig: Optional[str] = None

    @property
    def popups(self) -> "PopupGovernor":
        if self._popups is None:
            from ..guard.popup import PopupGovernor

            self._popups = PopupGovernor()
        return self._popups

    def reset(self) -> None:
        self._prev_screen_sig = None
        self._prev_text_sig = None

    def clear_baseline(self) -> None:
        """只作废「上一帧」比较基线，不影响调用方的连续故障计数。"""
        self._prev_screen_sig = None
        self._prev_text_sig = None

    def remember(self, report: HealthReport) -> None:
        """把某份体检结论登记为「上一帧」基线（由看门狗在决定不处置后调用）。"""
        self._prev_screen_sig = report.screen_sig
        self._prev_text_sig = report.text_sig

    def sample(self, screen: Optional[Screen] = None) -> HealthReport:
        """体检**并推进**比较基线（wait_for 等“以本帧为新基准”的场景使用）。"""
        report = self.evaluate(screen if screen is not None
                               else capture(self.device, self.ocr))
        self._prev_screen_sig = report.screen_sig
        self._prev_text_sig = report.text_sig
        return report

    def evaluate(self, screen: Screen) -> HealthReport:
        """只体检**不推进**基线：与 sample 分离，使「探测—决定不处置」不会吞掉冻结信号。"""
        screen_sig, text_sig = frame_signatures(screen)
        texts = _texts(screen)
        report = HealthReport(
            screen_sig=screen_sig,
            text_sig=text_sig,
            element_count=len(screen.elements),
            text_count=len(texts),
        )

        if report.element_count <= _BLANK_MAX_TEXTS and report.text_count <= _BLANK_MAX_TEXTS:
            report.blank = True
            report.health -= 0.45
            report.reasons.append("空白屏：未渲染出可见元素")
        if self._prev_screen_sig is not None and screen_sig == self._prev_screen_sig:
            report.frozen = True
            report.health -= 0.3
            report.reasons.append("画面冻结：与上一帧完全一致")
        pending = self.popups.find_pending(screen) if self._popups is not None else _popup_probe(screen)
        if pending is not None:
            kind, cand = pending
            report.popup_pending = True
            report.popup_title = cand.text or kind
            report.health -= 0.25
            report.reasons.append(f"弹窗拦截：{report.popup_title}")
        if report.element_count < _THIN_ELEMENTS:
            report.health -= 0.15
            report.reasons.append(f"元素稀薄：仅 {report.element_count} 个可交互节点")
        if report.text_count < _THIN_TEXTS:
            report.health -= 0.1
            report.reasons.append(f"文本稀薄：仅 {report.text_count} 条文本")

        report.health = round(max(0.0, min(1.0, report.health)), 3)
        return report


def format_health(r: HealthReport) -> str:
    flags = "/".join(n for n, on in (("空白", r.blank), ("冻结", r.frozen),
                                     ("弹窗", r.popup_pending)) if on) or "正常"
    detail = "；".join(r.reasons) if r.reasons else "无异常"
    return (f"健康度 {r.health:.2f} [{flags}] 元素 {r.element_count} 文本 {r.text_count} — {detail}")
