from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ElementSpec:
    """多通道元素规格：任一通道命中即可，按置信度融合排序。"""

    name: str
    texts: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    resource_ids: List[str] = field(default_factory=list)
    desc_contains: List[str] = field(default_factory=list)
    require_clickable: bool = False
    editable: bool = False
    template: Optional[str] = None
    template_threshold: float = 0.8
    prior: Optional[Tuple[float, float]] = None
    prior_radius: float = 0.3
    role: str = "button"

    @staticmethod
    def by_text(name: str, *texts: str, **kw) -> "ElementSpec":
        return ElementSpec(name=name, texts=list(texts), **kw)
