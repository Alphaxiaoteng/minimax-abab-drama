from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..device.base import Device, UiElement
from ..vision.base import OcrBackend, OcrHit, TemplateBackend

_FULL_TO_HALF = {0xFF01 + i: 0x21 + i for i in range(94)}
_FULL_TO_HALF[0x3000] = 0x20


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_FULL_TO_HALF)
    s = re.sub(r"\s+", "", s)
    return s.lower()


@dataclass
class Screen:
    width: int
    height: int
    elements: List[UiElement] = field(default_factory=list)
    ocr_hits: List[OcrHit] = field(default_factory=list)
    image: Optional[bytes] = None
    template_backend: Optional["TemplateBackend"] = None

    @property
    def has_ui_tree(self) -> bool:
        return bool(self.elements)

    def all_texts(self) -> List[str]:
        texts = [normalize_text(e.label()) for e in self.elements if e.label()]
        texts += [normalize_text(h.text) for h in self.ocr_hits]
        return [t for t in texts if t]

    def contains(self, needle: str) -> bool:
        n = normalize_text(needle)
        return any(n and n in t for t in self.all_texts())

    def find_all(self, pattern: str) -> List[str]:
        rx = re.compile(pattern)
        out = []
        for t in self.all_texts():
            out.extend(rx.findall(t))
        return out


def capture(device: Device, ocr: Optional[OcrBackend] = None,
            templates: Optional["TemplateBackend"] = None) -> Screen:
    w, h = device.resolution()
    elements = device.ui_dump()
    image = device.screenshot() if (ocr or templates) else None
    hits = ocr.ocr(image) if ocr else []
    return Screen(width=w, height=h, elements=elements, ocr_hits=hits, image=image,
                  template_backend=templates)
