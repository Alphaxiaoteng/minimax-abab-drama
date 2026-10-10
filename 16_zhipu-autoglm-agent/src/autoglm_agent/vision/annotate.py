from __future__ import annotations

"""把定位结果画回截图：评审看录屏时的“证据帧”。

自动化演示最容易被质疑的一点是“你到底点在哪、凭什么是这个元素”。
`annotate` 在截图上叠加候选框与通道/置信度标签，使每一步决策可被外部复核。
缺 Pillow 时安静返回 None（框架的降级约定），绝不因可视化缺失而中断业务。
"""

import io
from typing import Iterable, List, Optional, Tuple

from ..device.base import Bounds
from ..perception.screen import Screen

_COLOR_UI = (46, 160, 67)      # UI 树通道：绿
_COLOR_OCR = (31, 119, 180)    # OCR 通道：蓝
_COLOR_TPL = (255, 165, 0)     # 模板通道：橙
_COLOR_PRIOR = (200, 60, 60)   # 先验通道：红

_CHANNEL_COLOR = {
    "ui": _COLOR_UI, "ocr": _COLOR_OCR, "template": _COLOR_TPL, "prior": _COLOR_PRIOR,
}


def _color_for(source: str) -> Tuple[int, int, int]:
    return _CHANNEL_COLOR.get(source.split(":")[0], (120, 120, 120))


def annotate(image: Optional[bytes],
             hits: Iterable[Tuple[Bounds, str, float]],
             width: int = 3) -> Optional[bytes]:
    """在截图上画框并标注「通道 置信度」。返回 PNG bytes；Pillow 不可用返回 None。"""
    if not image:
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001 —— 缺依赖时静默降级
        return None
    try:
        base = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception:  # noqa: BLE001 —— 非图像负载（如虚拟设备 JSON）无法标注
        return None
    draw = ImageDraw.Draw(base)
    for bounds, label, conf in hits:
        color = _color_for(label)
        draw.rectangle([bounds.x1, bounds.y1, bounds.x2, bounds.y2], outline=color, width=width)
        text = f"{label} {conf:.2f}"
        tx, ty = bounds.x1, max(0.0, bounds.y1 - 14)
        draw.rectangle([tx, ty, tx + 8 * len(text), ty + 13], fill=color)
        draw.text((tx + 2, ty + 1), text, fill=(255, 255, 255))
    out = io.BytesIO()
    base.save(out, format="PNG")
    return out.getvalue()


def annotate_screen(screen: Screen, candidates=None) -> Optional[bytes]:
    """对整屏标注：所有 UI 元素（灰/绿）+ 候选（按通道着色）。

    `candidates` 省略时只画 UI 树元素，用于「这一帧我看到了什么」的证据图。
    """
    hits: List[Tuple[Bounds, str, float]] = []
    for el in screen.elements:
        bounds = el.bounds
        if el.clickable:
            hits.append((bounds, "ui", 1.0))
        else:
            hits.append((bounds, "text", 1.0))
    for cand in candidates or []:
        hits.append((cand.bounds, cand.source, cand.conf))
    return annotate(screen.image, hits)
