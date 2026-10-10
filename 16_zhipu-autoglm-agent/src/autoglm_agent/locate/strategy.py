from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ..device.base import Bounds
from ..perception.screen import Screen, normalize_text
from .spec import ElementSpec


@dataclass
class Candidate:
    bounds: Bounds
    center: Tuple[float, float]
    source: str
    conf: float
    text: str = ""
    editable: bool = False
    element_key: str = ""

    @property
    def shape(self) -> Tuple[float, float]:
        """候选目标形状（宽, 高）：用于动作前校验“屏幕没变、目标没漂”。"""
        return (self.bounds.x2 - self.bounds.x1, self.bounds.y2 - self.bounds.y1)


def _hit(bounds: Bounds, source: str, conf: float, text: str = "",
         editable: bool = False, element_key: Optional[str] = None) -> Candidate:
    """element_key 仅在 UI 树通道可给出；OCR/先验通道没有稳定元素身份，
    以归一化坐标键兜底，供动作前视觉自校验比较目标形状。"""
    if element_key is None:
        cx = round(bounds.center[0] / max(bounds.x2 - bounds.x1, 1.0), 2)
        cy = round(bounds.center[1] / max(bounds.y2 - bounds.y1, 1.0), 2)
        element_key = f"@{source}:{cx},{cy}"
    return Candidate(bounds=bounds, center=bounds.center, source=source, conf=conf,
                     text=text, editable=editable, element_key=element_key)


def _match_texts(norm_label: str, spec: ElementSpec) -> Tuple[float, bool]:
    """返回 (置信度, 是否命中)。0 表示未命中。"""
    for t in spec.texts:
        nt = normalize_text(t)
        if not nt:
            continue
        if norm_label == nt:
            return 0.98, True
        if nt in norm_label or norm_label in nt:
            ratio = difflib.SequenceMatcher(None, nt, norm_label).ratio()
            if norm_label and (nt in norm_label) and len(nt) >= 2:
                return max(0.85, ratio * 0.9), True
    for p in spec.patterns:
        try:
            if re.search(normalize_text(p), norm_label):
                return 0.9, True
        except re.error:
            continue
    for d in spec.desc_contains:
        if normalize_text(d) in norm_label:
            return 0.82, True
    return 0.0, False


def ui_tree_strategy(screen: Screen, spec: ElementSpec) -> List[Candidate]:
    out: List[Candidate] = []
    for el in screen.elements:
        if spec.require_clickable and not el.clickable:
            continue
        if spec.editable and not el.editable:
            continue
        if spec.resource_ids and el.rid and el.rid in spec.resource_ids:
            out.append(_hit(el.bounds, "ui:rid", 0.97, el.label(), el.editable,
                            str(el.extra.get("key", ""))))
            continue
        for raw in (el.text, el.desc):
            norm = normalize_text(raw)
            if not norm:
                continue
            conf, ok = _match_texts(norm, spec)
            if ok:
                src = "ui:text" if raw is el.text else "ui:desc"
                out.append(_hit(el.bounds, src, conf, raw, el.editable,
                                str(el.extra.get("key", ""))))
                break
    return out


def ocr_strategy(screen: Screen, spec: ElementSpec) -> List[Candidate]:
    out: List[Candidate] = []
    targets = [normalize_text(t) for t in spec.texts if t]
    for hit in screen.ocr_hits:
        norm = normalize_text(hit.text)
        if not norm:
            continue
        conf = 0.0
        for t in targets:
            if norm == t:
                conf = max(conf, 0.94 * (0.6 + 0.4 * hit.score))
            elif len(t) >= 2 and t in norm:
                conf = max(conf, 0.82 * (0.6 + 0.4 * hit.score))
            else:
                ratio = difflib.SequenceMatcher(None, t, norm).ratio()
                if ratio >= 0.72:
                    conf = max(conf, round(ratio * 0.8, 3))
        for p in spec.patterns:
            try:
                if re.search(normalize_text(p), norm):
                    conf = max(conf, 0.78)
            except re.error:
                continue
        if conf > 0:
            b = Bounds(*hit.bounds)
            out.append(_hit(b, "ocr", conf, hit.text))
    return out


def template_strategy(screen: Screen, spec: ElementSpec) -> List[Candidate]:
    """模板通道：UI 树缺节点 + OCR 不可用时（纯图像界面/自绘控件）兜底。
    置信度刻意压低（0.72 上限），让其只在与文本通道同分时参与裁决。"""
    tmpl = getattr(screen, "template_backend", None)
    if tmpl is None or not spec.template or not screen.image:
        return []
    try:
        hits = tmpl.match(screen.image, spec.template, threshold=spec.template_threshold)
    except NotImplementedError:
        return []
    except Exception:  # noqa: BLE001 —— 端侧视觉后端不可用不得中断定位
        return []
    out: List[Candidate] = []
    for h in hits:
        x1, y1, x2, y2 = h.bounds(screen.width, screen.height)
        out.append(_hit(Bounds(x1, y1, x2, y2), "template",
                        min(0.72, 0.6 + 0.2 * h.score), h.name))
    return out


def prior_strategy(screen: Screen, spec: ElementSpec) -> List[Candidate]:
    """最后兜底：按归一化坐标先验给一个低置信候选，容忍 UI 元素飘移。"""
    if spec.prior is None:
        return []
    x, y = spec.prior
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return []
    px, py = x * screen.width, y * screen.height
    half = 24
    return [_hit(Bounds(px - half, py - half, px + half, py + half), "prior", 0.52, "")]


Strategy = Callable[[Screen, ElementSpec], List[Candidate]]

DEFAULT_PIPELINE: List[Tuple[str, Strategy]] = [
    ("ui", ui_tree_strategy),
    ("ocr", ocr_strategy),
    ("template", template_strategy),
    ("prior", prior_strategy),
]
