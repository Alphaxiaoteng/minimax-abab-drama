from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class OcrHit:
    text: str
    center: Tuple[float, float]
    width: float = 0.0
    height: float = 0.0
    score: float = 0.9

    @property
    def bounds(self):
        x, y = self.center
        w = self.width or 120
        h = self.height or 48
        return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


class OcrBackend:
    name = "base"

    def ocr(self, image: Optional[bytes]) -> List[OcrHit]:
        raise NotImplementedError


@dataclass
class TemplateHit:
    """模板匹配命中：以中心点在图像中的归一化坐标 (0~1) 表达，
    与 OCR/UI 树候选落在同一坐标系，便于统一融合排序。"""

    name: str
    center: Tuple[float, float]
    score: float
    scale: float = 1.0

    def bounds(self, width: float, height: float) -> Tuple[float, float, float, float]:
        w = max(24.0, self.scale * self.width)
        h = max(24.0, self.scale * self.height)
        cx, cy = self.center[0] * width, self.center[1] * height
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    width: float = field(default=240.0, repr=False)
    height: float = field(default=96.0, repr=False)


class TemplateBackend:
    name = "base"

    def match(self, image: Optional[bytes], template_path: str,
              threshold: float = 0.8) -> List[TemplateHit]:
        raise NotImplementedError


class NullTemplate(TemplateBackend):
    name = "null"

    def match(self, image: Optional[bytes], template_path: str,
              threshold: float = 0.8) -> List[TemplateHit]:
        return []
