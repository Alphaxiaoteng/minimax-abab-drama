from __future__ import annotations

"""模板通道：UI 树没有节点、OCR 又读不出文字时的第三只眼。

端侧真实场景里，图标按钮（关闭/购物车/扫码）、自绘控件、Canvas 渲染的弹窗
既没有无障碍节点，也没有可识别文本——只有像素形状可辨。
本模块给出两种实现：
  - `ExampleTemplateBackend`：**零第三方依赖**，用「锚点表」描述模板形状，
    使模板通道在全离线环境（评审/CI）可被演示与测试；
  - `CvTemplateBackend`：有 numpy + OpenCV 时用真实图像做 `matchTemplate`。
真机接入只需把锚点表换成离线截取的模板 PNG 目录，上层融合逻辑完全不变。
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import TemplateBackend, TemplateHit


class ExampleTemplateBackend(TemplateBackend):
    """按名查锚点表命中：真实图片不可用时的确定性替身（不伪装成真实像素匹配）。"""

    name = "example-anchors"

    def __init__(self, templates: Optional[Dict[str, Any]] = None, default_score: float = 0.9):
        self.templates: Dict[str, Any] = {}
        self.default_score = default_score
        if templates:
            for key, val in templates.items():
                self.register(key, val if isinstance(val, list) else [val])

    def register(self, name: str, anchors, width: float = 240.0, height: float = 96.0) -> None:
        pts: List[Tuple[float, float]] = []
        for item in anchors or []:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pts.append((float(item[0]), float(item[1])))
        self.templates[name] = {"anchors": pts, "width": float(width), "height": float(height)}

    def load_dir(self, directory: str) -> int:
        """读取目录下的 `*.json` 锚点表：`{"anchors": [[x,y],…], "width":240, "height":96}`。"""
        n = 0
        for fn in sorted(os.listdir(directory)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(directory, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            name = payload.get("name") or os.path.splitext(fn)[0]
            self.register(name, payload.get("anchors"), payload.get("width", 240.0),
                          payload.get("height", 96.0))
            n += 1
        return n

    def _anchors_from_payload(self, image: Optional[bytes]) -> List[Tuple[float, float]]:
        """若截图是虚拟设备合成的 JSON（含元素坐标），用其元素中心作为锚点。"""
        if not image:
            return []
        try:
            payload = json.loads(image.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return []
        w = payload.get("width") or 0
        h = payload.get("height") or 0
        pts: List[Tuple[float, float]] = []
        for el in payload.get("elements", []):
            c = el.get("bounds") or [0, 0]
            if w and h:
                pts.append((c[0] / w, c[1] / h))
            else:
                pts.append((float(c[0]), float(c[1])))
        return pts

    def match(self, image: Optional[bytes], template_path: str,
              threshold: float = 0.8) -> List[TemplateHit]:
        if self.default_score < threshold:
            return []  # 阈值语义：要求高于本后端可达上限时直接判空
        name = os.path.splitext(os.path.basename(template_path or ""))[0]
        entry = self.templates.get(name)
        anchors: List[Tuple[float, float]] = []
        width, height = 240.0, 96.0
        if entry:
            anchors = list(entry.get("anchors") or [])
            width, height = entry.get("width", 240.0), entry.get("height", 96.0)
        if not anchors:
            anchors = self._anchors_from_payload(image)
        if not anchors:
            return []
        # 与图像元素中心做最近邻校验：命中数与匹配质量共同决定分数
        observed = self._anchors_from_payload(image)
        if observed:
            close = 0
            for ax, ay in anchors:
                if any(abs(ax - ox) + abs(ay - oy) < 0.05 for ox, oy in observed):
                    close += 1
            if close == 0:
                return []
            score = min(0.99, self.default_score + 0.09 * (close - 1))
        else:
            score = self.default_score
        center = (anchors[0][0], anchors[0][1])
        return [TemplateHit(name=name, center=center, score=round(score, 4),
                            scale=1.0, width=width, height=height)]


class CvTemplateBackend(TemplateBackend):
    """真实图像模板匹配（需要 numpy + OpenCV）。缺依赖时应由工厂降级到锚点后端。"""

    name = "opencv"

    def __init__(self):
        import cv2  # noqa: F401 —— 缺依赖时由 default_templates 捕获并降级
        import numpy  # noqa: F401

        self._cv2 = cv2
        self._np = numpy

    def match(self, image: Optional[bytes], template_path: str,
              threshold: float = 0.8) -> List[TemplateHit]:
        if not image or not template_path or not os.path.exists(template_path):
            return []
        cv2, np = self._cv2, self._np
        import io

        from PIL import Image

        screen = cv2.cvtColor(np.array(Image.open(io.BytesIO(image)).convert("RGB")),
                              cv2.COLOR_RGB2GRAY)
        tmpl = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            return []
        h, w = tmpl.shape[:2]
        if h > screen.shape[0] or w > screen.shape[1]:
            return []
        res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if float(max_val) < threshold:
            return []
        sh, sw = screen.shape[:2]
        cx = (max_loc[0] + w / 2.0) / max(sw, 1)
        cy = (max_loc[1] + h / 2.0) / max(sh, 1)
        name = os.path.splitext(os.path.basename(template_path))[0]
        return [TemplateHit(name=name, center=(cx, cy), score=round(float(max_val), 4),
                            width=float(w), height=float(h))]


def known_templates(scenario) -> Dict[str, Tuple[float, float]]:
    """从虚拟场景导出「元素 key → 归一化中心」锚点表（仅用于演示与单测）。

    真实工程中该表由离线截图生成，接口保持一致即可平滑替换。
    """
    out: Dict[str, Tuple[float, float]] = {}
    for screen in getattr(scenario, "screens", {}).values():
        for el in getattr(screen, "elements", []):
            out[el.key] = (el.x + el.w / 2.0, el.y + el.h / 2.0)
    return out


def default_templates(scenario=None, prefer_cv: bool = True) -> TemplateBackend:
    """有 OpenCV+PIL 用真实匹配；否则退回零依赖锚点后端（并注入虚拟场景锚点）。"""
    if prefer_cv:
        try:
            return CvTemplateBackend()
        except Exception:  # noqa: BLE001 —— 缺依赖属预期路径
            pass
    anchors = known_templates(scenario) if scenario is not None else {}
    return ExampleTemplateBackend(anchors)
