from __future__ import annotations

"""跨后端一致性：单一视觉通道的结果不得被当成事实。

端侧最容易出的错是**静默的错**——OCR 识别错一个字，仍以 0.86 的置信度被采信。
本模块要求“两个独立后端对同一目标给出相近结论”才算高可信：
  - `VisionConsistency`：虚拟 JSON OCR 通道与模板通道互为独立证据（真机上可换成
    rapidocr + OpenCV 模板两路），中心点相近或分数相近即视为一致。
  - `OcrConsistency`：连续多帧“同一画面且始终零命中”时，判定为“该页面确实无文本”
    （纯图标/自绘界面），从而使定位层不必空等 OCR 通道。
"""

import hashlib
import time
from typing import Any, Dict, List, Optional

from ..perception.screen import Screen, normalize_text
from ..vision.base import TemplateHit

_CENTER_TOL = 0.06      # 归一化中心曼哈顿距离阈值
_SCORE_TOL = 0.12       # 分数差阈值


def _center(hit: Any) -> Optional[tuple]:
    if isinstance(hit, TemplateHit):
        return tuple(hit.center)
    c = getattr(hit, "center", None)
    if isinstance(c, tuple) and len(c) == 2:
        return tuple(c)
    bounds = getattr(hit, "bounds", None)
    if bounds is not None and hasattr(bounds, "center"):
        return tuple(bounds.center)
    return None


def _score(hit: Any) -> float:
    for attr in ("score", "conf"):
        v = getattr(hit, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


class VisionConsistency:
    """按目标名缓存“最近一次各后端结论”，用于判断是否互相印证。"""

    def __init__(self, data_dir: str, max_age: float = 30.0):
        self.data_dir = data_dir
        self.max_age = max_age
        self._hits: Dict[str, List[Dict[str, Any]]] = {}
        self._frames: Dict[str, Dict[str, Any]] = {}
        self._max_frames = 16

    def reset(self) -> None:
        self._hits.clear()
        self._frames.clear()

    def capture(self, name: str, image: Optional[bytes], width: int, height: int) -> None:
        """记录某后端看到的一帧（只存摘要哈希，不驻留图像字节）。"""
        digest = hashlib.sha1(image).hexdigest()[:12] if image else ""
        self._frames[name] = {"sha1": digest, "w": width, "h": height, "ts": time.time()}
        if len(self._frames) > self._max_frames:
            oldest = min(self._frames, key=lambda k: self._frames[k]["ts"])
            self._frames.pop(oldest, None)

    def set(self, name: str, hit: Optional[Any], screen: Optional[Screen] = None) -> None:
        """登记某后端对当前目标的结论；`None` 表示该后端没看到。"""
        entry = {"hit": hit, "ts": time.time(),
                 "center": _center(hit) if hit is not None else None,
                 "score": _score(hit) if hit is not None else 0.0,
                 "text": getattr(hit, "text", "") if hit is not None else ""}
        self._hits.setdefault(name, []).append(entry)
        if len(self._hits[name]) > self._max_frames:
            self._hits[name] = self._hits[name][-self._max_frames:]

    def agree(self, name: str, other: Optional[Any]) -> bool:
        """`other` 为另一后端的结论；与已登记结论比对。"""
        if other is None:
            return False
        recent = self._recent(name)
        if not recent:
            return False
        c2 = _center(other)
        s2 = _score(other)
        for entry in recent:
            if entry["hit"] is other:
                return True  # 同源对象，无需再比
            c1 = entry["center"]
            if c1 is not None and c2 is not None:
                if abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) < _CENTER_TOL:
                    return True
            if entry["score"] and s2 and abs(entry["score"] - s2) < _SCORE_TOL:
                return True
            t1, t2 = entry["text"], getattr(other, "text", "")
            if t1 and t2 and normalize_text(t1) == normalize_text(t2):
                return True
        return False

    def consensus(self, name: str) -> bool:
        """最近 max_age 秒内是否有 ≥2 条不同后端的相近结论。"""
        return len(self._recent(name)) >= 2

    def _recent(self, name: str) -> List[Dict[str, Any]]:
        now = time.time()
        items = [e for e in self._hits.get(name, []) if now - e["ts"] <= self.max_age]
        self._hits[name] = items
        return items


class OcrConsistency:
    """零命中稳定性判定：连续多次相同画面且始终没有文本 → 该页面确实无文本。"""

    def __init__(self, min_agree: int = 2):
        self.min_agree = min_agree
        self._empty_sig: Optional[str] = None
        self._empty_streak = 0

    def reset(self) -> None:
        self._empty_sig = None
        self._empty_streak = 0

    @staticmethod
    def _signature(screen: Screen) -> str:
        texts = [normalize_text(e.label()) for e in screen.elements if e.label()]
        payload = "|".join(sorted(t for t in texts if t))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def observe(self, screen: Screen) -> None:
        if screen.ocr_hits:
            self._empty_sig = None
            self._empty_streak = 0
            return
        sig = self._signature(screen)
        if sig == self._empty_sig:
            self._empty_streak += 1
        else:
            self._empty_sig = sig
            self._empty_streak = 1

    def stable_empty(self, screen: Screen, min_obs: int = 2) -> bool:
        """不改变计数地查询：当前帧是否命中“确认无文本”。"""
        if screen.ocr_hits:
            return False
        threshold = max(self.min_agree, min_obs)
        return self._empty_streak >= threshold and self._empty_sig == self._signature(screen)
