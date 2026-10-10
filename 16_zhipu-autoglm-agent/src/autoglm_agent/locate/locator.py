from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

from ..config import Settings
from ..device.base import Device
from ..perception.screen import Screen, capture
from ..vision.base import OcrBackend
from .spec import ElementSpec
from .strategy import Candidate, DEFAULT_PIPELINE, Strategy


class LocateError(RuntimeError):
    pass


class FaultTolerantLocator:
    """多策略融合定位：便宜通道先行、歧义二次确认、找不到时滚动探测。"""

    accept_conf = 0.93
    ambiguous_gap = 0.06
    consensus_bonus = 0.015

    def __init__(self, device: Device, settings: Settings,
                 ocr: Optional[OcrBackend] = None,
                 pipeline: Optional[List[Tuple[str, Strategy]]] = None,
                 templates: Optional[TemplateBackend] = None):
        self.device = device
        self.s = settings
        self.ocr = ocr
        self.templates = templates
        self.pipeline = pipeline or DEFAULT_PIPELINE

    def snapshot(self) -> Screen:
        return capture(self.device, self.ocr, self.templates)

    def candidates(self, screen: Screen, spec: ElementSpec) -> List[Candidate]:
        out: List[Candidate] = []
        for _, strategy in self.pipeline:
            out.extend(strategy(screen, spec))
        return self._dedupe(out)

    def _fuse(self, cands: List[Candidate]) -> List[Candidate]:
        """同位置多通道互相印证（如 UI 树与 OCR 同时命中）加小分：
        这是“看得见 + 点得到”的双重证据，比单通道高置信更可信。"""
        groups: dict = {}
        for c in cands:
            groups.setdefault((round(c.center[0] / 8), round(c.center[1] / 8)), []).append(c)
        for group in groups.values():
            sources = {c.source.split(":")[0] for c in group}
            if len(sources) < 2:
                continue
            best = max(group, key=lambda c: c.conf)
            if best.conf >= 0.7:
                best.conf = min(0.99, best.conf + self.consensus_bonus)
        return cands

    @staticmethod
    def _dedupe(cands: List[Candidate]) -> List[Candidate]:
        seen = {}
        for c in cands:
            key = (round(c.center[0] / 8), round(c.center[1] / 8))
            if key not in seen or seen[key].conf < c.conf:
                seen[key] = c
        return sorted(seen.values(), key=lambda c: -c.conf)

    def _rank(self, cands: List[Candidate], spec: ElementSpec) -> List[Candidate]:
        w, h = self.device.resolution()

        def prior_dist(c: Candidate) -> float:
            if spec.prior is None:
                return 1e9
            tx, ty = spec.prior[0] * w, spec.prior[1] * h
            dx, dy = c.center[0] - tx, c.center[1] - ty
            radius = spec.prior_radius * min(w, h)
            d = (dx * dx + dy * dy) ** 0.5
            return d + (10 * radius if d > radius else 0.0)

        return sorted(cands, key=lambda c: (-c.conf, prior_dist(c)))

    def find(self, spec: ElementSpec, screen: Optional[Screen] = None,
             allow_fallback: bool = False) -> Optional[Candidate]:
        screen = screen or self.snapshot()
        ranked = self._rank(self._fuse(self.candidates(screen, spec)), spec)
        if not ranked:
            return None
        top = ranked[0]
        if top.conf >= self.accept_conf:
            return top
        if len(ranked) > 1 and top.conf - ranked[1].conf < self.ambiguous_gap:
            # 歧义：二次采样，要求两个候选中心稳定重合才信任
            stable = self._confirm(ranked[:3], spec)
            return stable or top
        if top.conf >= 0.7:
            return top
        # 低于阈值：模板/先验属于“赌一把”的兜底通道，只能由 locate 在超时后显式放行
        if allow_fallback and top.source in ("template", "prior"):
            return top
        return None

    def _confirm(self, cands: List[Candidate], spec: ElementSpec) -> Optional[Candidate]:
        time.sleep(self.s.locate_poll_interval)
        again = self._rank(self.candidates(self.snapshot(), spec), spec)
        for c in cands:
            for a in again[:5]:
                if abs(a.center[0] - c.center[0]) < 24 and abs(a.center[1] - c.center[1]) < 24:
                    return max(c, a, key=lambda x: x.conf)
        return None

    def locate(self, spec: ElementSpec, timeout: Optional[float] = None,
               scroll_probe: bool = True,
               on_miss: Optional[Callable[[], None]] = None) -> Candidate:
        timeout = self.s.locate_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        probes = 0
        while True:
            cand = self.find(spec)
            if cand:
                return cand
            if scroll_probe and probes < self.s.max_scroll_probe:
                probes += 1
                found = self._scroll_probe(spec)
                if found:
                    return found
            if on_miss:
                on_miss()
            if probes == 0 and not scroll_probe:
                pass  # 未开启滚动探测：纯轮询等待，交由下面的 deadline 判定
            elif probes == 0 and time.monotonic() >= deadline and self.s.max_scroll_probe > 0:
                break  # 等待预算耗尽且一次都未滚动：直接走超时后的兜底通道
            if time.monotonic() >= deadline:
                last = self.find(spec, screen=self.snapshot(), allow_fallback=True)
                if last and last.source in ("prior", "template"):
                    return last
                raise LocateError(
                    f"定位失败 [{spec.name}]：{timeout:.1f}s 内未找到元素（texts={spec.texts}, patterns={spec.patterns}）")
            time.sleep(self.s.locate_poll_interval)

    def _scroll_probe(self, spec: ElementSpec) -> Optional[Candidate]:
        """单次探测：最多滚动 max_scroll_probe 次，命中即返回，未命中滚回顶部。
        预算由 locate 的调用次数控制，避免无限循环里重复空滚。"""
        seen_signatures = set()
        for _ in range(max(1, self.s.max_scroll_probe)):
            self.device.scroll_down(0.5)
            time.sleep(self.s.scroll_settle)
            screen = self.snapshot()
            cand = self.find(spec, screen=screen)
            if cand:
                for _ in range(len(seen_signatures)):
                    self.device.scroll_up(0.7)
                return cand
            sig = "|".join(screen.all_texts()[:20])
            if sig in seen_signatures:
                break
            seen_signatures.add(sig)
        # 回滚到顶，避免影响后续步骤
        for _ in range(len(seen_signatures) + 1):
            self.device.scroll_up(0.7)
        return None
