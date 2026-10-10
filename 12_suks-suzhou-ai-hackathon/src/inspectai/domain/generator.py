"""合成工业质检数据集生成器（S2 · SyntheticPartGenerator）。

用纯 numpy + cv2 按场景工艺先验合成 4 大典型件的质检图，并产出 ``GroundTruth``。
所有随机性统一由 ``numpy.random.default_rng`` 派生，禁止使用全局 ``np.random``；
因此 ``seed`` 固定时逐图、整批、落盘都完全可复现。

设计约束
--------
* 主流程（合成底图 → 渲染缺陷 → 成像链 → 量化）对场景无感，场景差异只通过
  :data:`SCENE_PROFILES` 与模块级**纹理表**取参数/取函数，不写 ``if scene==…`` 流程分支。
* 每类缺陷的几何与灰度幅值刻意对齐 :func:`inspectai.contracts.classify_region` 的
  不变量：划伤细长（高长宽比、线性连通）、气孔为暗圆簇（紧凑连通、中心最深）、
  压痕近圆/圆角（各向同性、可亮可暗）、油污为高亮不规则斑（多椭圆并集）。
* 缺陷完全落在图内、真值框互斥（成对 IoU ≤ 0.1），局部光照块平滑低幅，
  保证"不凭空造缺陷"。
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable

import cv2
import numpy as np

from ..contracts import (
    CLASS_CONTAMINATION,
    CLASS_INDENTATION,
    CLASS_POROSITY,
    CLASS_SCRATCH,
    SCENE_PROFILES,
    SC_BEARING,
    SC_CASTING,
    SC_GEAR,
    SC_STAMPING,
    DEFAULT_CONFIG,
    DEFECT_CLASSES,
    SceneProfile,
    clamp01,
)
from .groundtruth import Annotation, GroundTruth, bbox_iou, write_manifest

_TWO_PI = 2.0 * math.pi

# --------------------------------------------------------------------------------------
# 场景纹理表（唯一按 scene_id 分派之处；流程其余部分完全参数化）
# --------------------------------------------------------------------------------------


def _tex_gear(p: SceneProfile, xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """齿面加工纹：周期 ~9px 的正弦条带 + 沿程慢变包络。"""
    period = float(p.period_hint) if p.period_hint else 9.0
    phi = float(rng.uniform(0.0, _TWO_PI))
    return 9.0 * np.sin(_TWO_PI * xs / period + phi) * (1.0 + 0.3 * np.sin(_TWO_PI * ys / (period * 7.0)))


def _tex_bearing(p: SceneProfile, xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """滚道同心圆磨削纹：半径场上的正弦环带。"""
    period = float(p.period_hint) if p.period_hint else 18.0
    h, w = xs.shape
    r = np.hypot(xs - w / 2.0, ys - h / 2.0)
    phi = float(rng.uniform(0.0, _TWO_PI))
    return 11.0 * np.sin(_TWO_PI * r / period + phi)


def _tex_casting(p: SceneProfile, xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """压铸面：各向同性白噪 + 大尺度低频起伏。"""
    h, w = xs.shape
    grain = rng.standard_normal((h, w)).astype(np.float32) * 7.0
    lf = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 30.0)
    lf = lf - float(lf.mean())
    lf = (lf / (float(lf.std()) + 1e-6)) * 6.0
    return grain + lf.astype(np.float32)


def _tex_stamping(p: SceneProfile, xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """拉延变形纹：低频正弦场 + 平面倾斜光照 a*x+b*y。"""
    period = float(p.period_hint) if p.period_hint else 34.0
    phi = float(rng.uniform(0.0, _TWO_PI))
    phi2 = float(rng.uniform(0.0, _TWO_PI))
    a = float(rng.uniform(-0.015, 0.015))
    b = float(rng.uniform(-0.015, 0.015))
    wave = 14.0 * np.sin(_TWO_PI * xs / period + phi) * np.sin(_TWO_PI * ys / (period * 4.0) + phi2)
    return wave + (a * xs + b * ys)


_TEXTURE_BUILDERS: dict[str, Callable[[SceneProfile, np.ndarray, np.ndarray, np.random.Generator], np.ndarray]] = {
    SC_GEAR: _tex_gear,
    SC_BEARING: _tex_bearing,
    SC_CASTING: _tex_casting,
    SC_STAMPING: _tex_stamping,
}


def _tight_bbox(patch: np.ndarray, rel: float = 0.2) -> tuple[int, int, int, int]:
    """按峰值相对阈值取紧凑 (x, y, w, h)，裁掉高斯拖尾，避免真值框被低信号裙边稀释。"""
    peak = float(np.abs(patch).max())
    thr = max(0.5, rel * peak)
    m = np.abs(patch) >= thr
    ys = np.where(m.any(axis=1))[0]
    xs = np.where(m.any(axis=0))[0]
    if len(ys) == 0 or len(xs) == 0:
        h, w = patch.shape
        return 0, 0, int(w), int(h)
    y0, y1 = int(ys[0]), int(ys[-1])
    x0, x1 = int(xs[0]), int(xs[-1])
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


# --------------------------------------------------------------------------------------
# 缺陷渲染器：每个返回 (紧凑 patch, features, score)
# patch 为加性灰度（float32，暗为负、亮为正），已裁到缺陷紧凑包围盒。
# --------------------------------------------------------------------------------------


def _render_scratch(rng: np.random.Generator, scale: float) -> tuple[np.ndarray, dict[str, float], float]:
    length = float(rng.uniform(40.0, 180.0)) * scale
    theta = float(rng.uniform(0.0, math.pi))
    width = float(rng.uniform(1.0, 3.0))
    amp = float(rng.uniform(1.5, 4.0))
    depth = float(rng.uniform(30.0, 70.0))
    wfreq = float(rng.uniform(1.0, 3.0))
    wphase = float(rng.uniform(0.0, _TWO_PI))

    extent_x = abs(math.cos(theta)) * length + amp
    extent_y = abs(math.sin(theta)) * length + amp
    pw = max(3, int(math.ceil(extent_x)) + 4)
    ph = max(3, int(math.ceil(extent_y)) + 4)
    Y, X = np.mgrid[0:ph, 0:pw].astype(np.float32)
    delta = np.zeros((ph, pw), dtype=np.float32)
    cx0 = pw / 2.0
    cy0 = ph / 2.0
    steps = max(24, int(length * 1.2))
    ct, st = math.cos(theta), math.sin(theta)
    sigma2 = 2.0 * (width * width)
    for i in range(steps + 1):
        t = i / steps
        s = t - 0.5
        wob = amp * math.sin(_TWO_PI * wfreq * t + wphase)
        px = cx0 - ct * length * s - st * wob
        py = cy0 - st * length * s + ct * wob
        end = min(t, 1.0 - t)
        fade = math.exp(-(end * end) / (2.0 * 0.05 * 0.05))
        g = np.exp(-((X - px) ** 2 + (Y - py) ** 2) / sigma2).astype(np.float32)
        delta -= (g * np.float32(depth * fade)).astype(np.float32)

    x, y, w, h = _tight_bbox(delta)
    patch = delta[y:y + h, x:x + w]
    feats = {
        "length": round(length, 2),
        "width": round(width, 2),
        "depth": round(depth, 2),
        "contrast": round(clamp01(depth / 70.0), 4),
    }
    score = round(clamp01(0.35 + 0.5 * feats["contrast"]), 3)
    return patch, feats, score


def _render_porosity(rng: np.random.Generator, scale: float) -> tuple[np.ndarray, dict[str, float], float]:
    n = int(rng.integers(3, 13))
    patch_n = int(rng.integers(22, 30)) + int(scale * 4)
    Y, X = np.mgrid[0:patch_n, 0:patch_n].astype(np.float32)
    delta = np.zeros((patch_n, patch_n), dtype=np.float32)
    core = patch_n / 2.0
    depths: list[float] = []
    for _ in range(n):
        sx = core + float(rng.uniform(-5.0, 5.0))
        sy = core + float(rng.uniform(-5.0, 5.0))
        rad = float(rng.uniform(2.0, 6.0))
        depth = float(rng.uniform(35.0, 70.0))
        g = np.exp(-((X - sx) ** 2 + (Y - sy) ** 2) / (2.0 * rad * rad)).astype(np.float32)
        delta -= (g * np.float32(depth)).astype(np.float32)
        depths.append(depth)
    dmax = max(depths)
    x, y, w, h = _tight_bbox(delta)
    patch = delta[y:y + h, x:x + w]
    feats = {
        "length": round(float(max(h, w)), 2),
        "width": round(float(min(h, w)), 2),
        "depth": round(dmax, 2),
        "contrast": round(clamp01(dmax / 80.0), 4),
    }
    score = round(clamp01(0.35 + 0.5 * feats["contrast"]), 3)
    return patch, feats, score


def _render_indentation(rng: np.random.Generator, scale: float) -> tuple[np.ndarray, dict[str, float], float]:
    diameter = float(rng.uniform(18.0, 45.0)) * scale
    a = diameter / 2.0
    b = a * float(rng.uniform(0.6, 1.0))
    sig = float(rng.uniform(2.0, 4.0))
    pad = int(math.ceil(sig * 3.0)) + 3
    ph = int(math.ceil(b * 2.0)) + 2 * pad + 1
    pw = int(math.ceil(a * 2.0)) + 2 * pad + 1
    Y, X = np.mgrid[0:ph, 0:pw].astype(np.float32)
    cx = pw / 2.0
    cy = ph / 2.0
    ellipse = ((X - cx) / a) ** 2 + ((Y - cy) / b) ** 2
    body = (ellipse <= 1.0).astype(np.float32)
    mag = float(rng.uniform(15.0, 25.0))
    sign = 1.0 if rng.random() < 0.5 else -1.0
    soft = cv2.GaussianBlur(body * np.float32(mag), (0, 0), sig).astype(np.float32)
    delta = (soft * np.float32(sign)).astype(np.float32)
    x, y, w, h = _tight_bbox(delta)
    patch = delta[y:y + h, x:x + w]
    feats = {
        "length": round(diameter, 2),
        "width": round(2.0 * b, 2),
        "depth": round(mag, 2),
        "contrast": round(clamp01(mag / 40.0), 4),
    }
    score = round(clamp01(0.30 + 0.5 * feats["contrast"]), 3)
    return patch, feats, score


def _render_contamination(rng: np.random.Generator, scale: float) -> tuple[np.ndarray, dict[str, float], float]:
    n_ell = int(rng.integers(3, 7))
    base = float(rng.uniform(20.0, 50.0)) * scale
    sig = 3.0
    pad = 8
    ph = int(base) + 2 * pad + 1
    pw = int(base) + 2 * pad + 1
    Y, X = np.mgrid[0:ph, 0:pw].astype(np.float32)
    mask = np.zeros((ph, pw), dtype=np.float32)
    depth = float(rng.uniform(25.0, 55.0))
    for _ in range(n_ell):
        cx = float(rng.uniform(pad, pw - pad))
        cy = float(rng.uniform(pad, ph - pad))
        ea = float(rng.uniform(base * 0.3, base * 0.6))
        eb = ea * float(rng.uniform(0.6, 1.0))
        th = float(rng.uniform(0.0, math.pi))
        dx = X - cx
        dy = Y - cy
        rx = dx * math.cos(th) + dy * math.sin(th)
        ry = -dx * math.sin(th) + dy * math.cos(th)
        one = (((rx / ea) ** 2 + (ry / eb) ** 2) <= 1.0).astype(np.float32)
        mask = np.maximum(mask, one)
    delta = cv2.GaussianBlur(mask * np.float32(depth), (0, 0), sig).astype(np.float32)
    x, y, w, h = _tight_bbox(delta)
    patch = delta[y:y + h, x:x + w]
    feats = {
        "length": round(float(h), 2),
        "width": round(float(w), 2),
        "depth": round(depth, 2),
        "contrast": round(clamp01(depth / 60.0), 4),
    }
    score = round(clamp01(0.30 + 0.5 * feats["contrast"]), 3)
    return patch, feats, score


_DEFECT_RENDERERS: dict[str, Callable[[np.random.Generator, float], tuple[np.ndarray, dict[str, float], float]]] = {
    CLASS_SCRATCH: _render_scratch,
    CLASS_POROSITY: _render_porosity,
    CLASS_INDENTATION: _render_indentation,
    CLASS_CONTAMINATION: _render_contamination,
}


def _class_weights(scene_id: str) -> np.ndarray:
    """按 ``DEFAULT_CONFIG.class_prior_from_scene`` 构造 4 类采样权重（用契约参数，非硬编码）。"""
    weights = {c: 1.0 for c in DEFECT_CLASSES}
    prior = DEFAULT_CONFIG.class_prior_from_scene.get(scene_id)
    if prior is not None:
        p_class, p_w = prior
        weights[p_class] = 1.0 + 2.0 * float(p_w)
    arr = np.array([weights[c] for c in DEFECT_CLASSES], dtype=np.float64)
    return arr / arr.sum()


class SyntheticPartGenerator:
    """按场景工艺先验合成质检图与真值的生成器。"""

    def __init__(
        self,
        scene_id: str = SC_GEAR,
        seed: int | None = None,
        size: tuple[int, int] = (900, 1200),
    ) -> None:
        if scene_id not in SCENE_PROFILES:
            raise ValueError(f"未知 scene_id={scene_id!r}，可选 {sorted(SCENE_PROFILES)}")
        self.scene_id = scene_id
        self.profile: SceneProfile = SCENE_PROFILES[scene_id]
        self._seed = int(self.profile.seed) if seed is None else int(seed)
        self.h, self.w = int(size[0]), int(size[1])
        self._class_p = _class_weights(scene_id)
        self._ok_seq = 0
        self._ng_seq = 0
        self._call_seq = 0

    # ---- 内部合成 ----

    def _base(self, rng: np.random.Generator) -> np.ndarray:
        ys, xs = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        builder = _TEXTURE_BUILDERS.get(self.scene_id, _tex_gear)
        texture = np.asarray(builder(self.profile, xs, ys, rng), dtype=np.float32)
        return np.float32(self.profile.background) + texture

    def _place_defects(self, rng: np.random.Generator, n: int) -> tuple[np.ndarray, list[Annotation]]:
        scale = float(self.profile.defect_scale)
        delta = np.zeros((self.h, self.w), dtype=np.float32)
        placed: list[tuple[int, int, int, int]] = []
        anns: list[Annotation] = []
        for _ in range(n):
            cls = str(rng.choice(DEFECT_CLASSES, p=self._class_p))
            patch, feats, score = _DEFECT_RENDERERS[cls](rng, scale)
            ph, pw = patch.shape
            if pw > self.w or ph > self.h:
                # 极端尺寸（几乎不可能）：收缩到图内
                ph = min(ph, self.h)
                pw = min(pw, self.w)
                patch = patch[:ph, :pw]
            for attempt in range(50):
                x0 = int(rng.integers(0, self.w - pw + 1))
                y0 = int(rng.integers(0, self.h - ph + 1))
                bbox = (x0, y0, pw, ph)
                if all(bbox_iou(bbox, p) <= 0.1 for p in placed):
                    break
            else:
                # 重试耗尽：退化为顺序不重叠放置（仍保证图内、互斥）
                x0 = int(min(rng.integers(0, self.w - pw + 1), max(0, self.w - pw)))
                y0 = int(min(rng.integers(0, self.h - ph + 1), max(0, self.h - ph)))
                if x0 + pw > self.w:
                    x0 = self.w - pw
                if y0 + ph > self.h:
                    y0 = self.h - ph
                bbox = (x0, y0, pw, ph)
                if any(bbox_iou(bbox, p) > 0.1 for p in placed):
                    continue  # 实在放不下则跳过该缺陷，避免污染真值
            delta[y0:y0 + ph, x0:x0 + pw] += patch
            placed.append(bbox)
            anns.append(Annotation(defect_class=cls, bbox=bbox, score=float(score), features=feats))
        return delta, anns

    def _imaging_chain(self, img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        # 读出噪声
        img = img + (rng.standard_normal(img.shape) * 2.5).astype(np.float32)
        # 轻微暗角
        ys, xs = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        r = np.hypot(xs - self.w / 2.0, ys - self.h / 2.0)
        rmax = float(r.max()) + 1e-6
        img = img * (1.0 - 0.08 * (r / rmax) ** 1.6)
        # 5% 概率局部高光/阴影块（平滑、低幅 → 检测器应判 pass/review，不造缺陷）
        if rng.random() < 0.05:
            bh = int(rng.integers(max(4, self.h // 8), max(8, self.h // 4)))
            bw = int(rng.integers(max(4, self.w // 8), max(8, self.w // 4)))
            by = int(rng.integers(0, max(1, self.h - bh)))
            bx = int(rng.integers(0, max(1, self.w - bw)))
            val = float(rng.uniform(-22.0, 22.0))
            block = np.zeros((self.h, self.w), dtype=np.float32)
            block[by:by + bh, bx:bx + bw] = val
            block = cv2.GaussianBlur(block, (0, 0), float(min(bh, bw) / 3.0))
            img = img + block
        return img

    def _render(self, rng: np.random.Generator, has_defect: bool, n_defects: int | None, image_id: str) -> tuple[np.ndarray, GroundTruth]:
        img = self._base(rng)
        anns: list[Annotation] = []
        if has_defect:
            if n_defects is None:
                n = int(rng.integers(1, 4))
            else:
                n = max(0, int(n_defects))
            delta, anns = self._place_defects(rng, n)
            img = img + delta
        img = self._imaging_chain(img, rng)
        arr = np.clip(np.round(img), 0.0, 255.0).astype(np.uint8)
        gt = GroundTruth(
            image_id=image_id,
            scene_id=self.scene_id,
            image_path=f"images/{image_id}.png",
            annotations=anns,
        )
        return arr, gt

    # ---- 公开 API ----

    def generate(self, has_defect: bool = True, n_defects: int | None = None) -> tuple[np.ndarray, GroundTruth]:
        """生成一张图。同 seed 的**首个** ``generate()`` 结果可复现（新实例首调用一致）。"""
        rng = np.random.default_rng(self._seed + self._call_seq)
        self._call_seq += 1
        if has_defect:
            image_id = f"{self.scene_id}_ng_{self._ng_seq:04d}"
            self._ng_seq += 1
        else:
            image_id = f"{self.scene_id}_ok_{self._ok_seq:04d}"
            self._ok_seq += 1
        return self._render(rng, has_defect, n_defects, image_id)

    def generate_batch(
        self,
        n_ok: int,
        n_ng: int,
        defects_per_image: tuple[int, int] = (1, 3),
    ) -> list[tuple[np.ndarray, GroundTruth]]:
        """批量生成 ``n_ok`` 张合格图 + ``n_ng`` 张缺陷图，**确定性**：同 seed 两次调用逐图一致。"""
        lo, hi = int(defects_per_image[0]), int(defects_per_image[1])
        if hi < lo:
            lo, hi = hi, lo
        out: list[tuple[np.ndarray, GroundTruth]] = []
        idx = 0
        for i in range(n_ok):
            rng = np.random.default_rng(self._seed + 1000 * idx)
            out.append(self._render(rng, False, 0, f"{self.scene_id}_ok_{i:04d}"))
            idx += 1
        for i in range(n_ng):
            rng = np.random.default_rng(self._seed + 1000 * idx)
            n = int(rng.integers(lo, hi + 1))
            out.append(self._render(rng, True, n, f"{self.scene_id}_ng_{i:04d}"))
            idx += 1
        return out

    def save_dataset(self, root: str, n_ok: int = 30, n_ng: int = 40) -> str:
        """落盘 ``root/images/*.png`` 与 ``root/manifest.json``，返回 manifest 路径。"""
        img_dir = os.path.join(root, "images")
        os.makedirs(img_dir, exist_ok=True)
        batch = self.generate_batch(n_ok, n_ng)
        truths: list[GroundTruth] = []
        for arr, gt in batch:
            cv2.imwrite(os.path.join(img_dir, f"{gt.image_id}.png"), arr)
            truths.append(gt)
        manifest_path = os.path.join(root, "manifest.json")
        write_manifest(truths, manifest_path)
        return manifest_path


__all__ = ["SyntheticPartGenerator"]