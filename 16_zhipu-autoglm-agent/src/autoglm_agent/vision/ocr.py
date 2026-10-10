from __future__ import annotations

import json
import logging
from typing import List, Optional

from .base import OcrBackend, OcrHit


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
        import numpy as np
        from PIL import Image
        import io

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


def default_ocr(for_virtual: bool) -> OcrBackend:
    if for_virtual:
        return VirtualJsonOcr()
    try:
        return RapidOcr()
    except Exception:
        return NullOcr()
