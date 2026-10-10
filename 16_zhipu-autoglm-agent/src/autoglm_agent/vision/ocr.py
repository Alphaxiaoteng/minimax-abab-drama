from __future__ import annotations

import json
import logging
from typing import List, Optional

from .base import OcrBackend, OcrHit

log = logging.getLogger(__name__)


class NullOcr(OcrBackend):
    name = "null"

    def ocr(self, image: Optional[bytes]) -> List[OcrHit]:
        return []


class VirtualJsonOcr(OcrBackend):
    """读取 VirtualDevice 合成的 screenshot 负载（JSON），模拟带噪声的 OCR 结果。"""

    name = "virtual-json"

    def ocr(self, image: Optional[bytes]) -> List[OcrHit]:
        if not image:
            return []
        try:
            payload = json.loads(image.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        hits = []
        for el in payload.get("elements", []):
            text = (el.get("text") or el.get("desc") or "").strip()
            if not text:
                continue
            c = el.get("bounds") or [0, 0]
            hits.append(OcrHit(text=text, center=(c[0], c[1]), width=140, height=48, score=0.86))
        return hits


class RapidOcr(OcrBackend):
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR  # 可选依赖

        self._engine = RapidOCR()

    def ocr(self, image: Optional[bytes]) -> List[OcrHit]:
        if not image:
            return []
        import io

        import numpy as np
        from PIL import Image

        img = np.array(Image.open(io.BytesIO(image)).convert("RGB"))
        result, _ = self._engine(img)
        hits = []
        for box, text, score in (result or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            hits.append(OcrHit(
                text=text,
                center=(sum(xs) / len(xs), sum(ys) / len(ys)),
                width=max(xs) - min(xs),
                height=max(ys) - min(ys),
                score=float(score),
            ))
        return hits


class OcrConsensus(OcrBackend):
    """多 OCR 后端投票：单通道识别到的文本降权，两路以上互证才给满分。

    端侧判据：同一文本被两个独立模型同时读出，几乎不可能是幻觉；
    只有一路读出时可能是噪声，故把置信度打 0.85 折，交由定位层做二次确认。
    """

    name = "consensus"
    single_backend_factor = 0.85

    def __init__(self, backends: List[OcrBackend], single_factor: float = 0.85):
        self.backends = [b for b in backends if b is not None]
        self.single_factor = single_factor

    def ocr(self, image: Optional[bytes]) -> List[OcrHit]:
        from ..perception.screen import normalize_text

        merged: dict = {}
        votes: dict = {}
        for idx, backend in enumerate(self.backends):
            try:
                hits = backend.ocr(image) or []
            except Exception:  # noqa: BLE001 —— 单后端故障不得拖垮感知层
                continue
            for h in hits:
                key = normalize_text(h.text)
                if not key:
                    continue
                if key not in merged or h.score > merged[key].score:
                    merged[key] = h
                votes.setdefault(key, set()).add(idx)
        out: List[OcrHit] = []
        for key, hit in merged.items():
            factor = 1.0 if len(votes[key]) >= 2 else self.single_factor
            out.append(OcrHit(text=hit.text, center=hit.center, width=hit.width,
                              height=hit.height, score=round(hit.score * factor, 4)))
        return out


def default_ocr(for_virtual: bool) -> OcrBackend:
    if for_virtual:
        return VirtualJsonOcr()
    try:
        return RapidOcr()
    except Exception:
        return NullOcr()
