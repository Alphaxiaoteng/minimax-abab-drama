"""缺陷检测核心引擎（S1 · Detector Core）。

实现「结构化残差 + 局部对比度 + 纹理异常」三通道并行、多尺度形态学增强、
结构性抑制与多分辨率连通域分析的完整流水线，输出契约冻结的
:class:`~inspectai.contracts.DetectionResult`。

设计原则
--------
* 纯 CPU、确定性：同一输入两次运行逐字段一致（无随机源、无状态残留）。
* 周期纹理优先抑制：齿轮/轴承工件的纹理是"背景"，只有偏离结构的部分才是缺陷，
  故主通道用频域陷波重建背景后取残差，而不是简单阈值分割。
* 所有阈值/权重取自 :data:`~inspectai.contracts.DEFAULT_CONFIG`；本模块只保留
  与评分无关的工程常数（下采样尺寸、融合权重、陷波宽度系数等）。

坐标基准
--------
连通域统计（``bbox`` / ``centroid`` / ``area_px``）全部落在**底分辨率热力图**
（长边 ≤ 384）坐标系，即 ``DetectionResult.heatmap_shape``；原分辨率仅用于
计算几何/纹理属性与叠加缩放。
"""

from __future__ import annotations

import base64
import math
import time
from functools import lru_cache

import cv2
import numpy as np

from inspectai.contracts import (
    DEFAULT_CONFIG,
    MAX_OVERLAY_PX,
    SCENE_PROFILES,
    DetectionResult,
    DefectItem,
    InspectionConfig,
    RegionStat,
    aggregate_score,
    clamp01,
    classify_region,
    decide,
    region_score,
    region_stats,
    score_to_severity,
)

# --------------------------------------------------------------------------------------
# 工程常数（不进入契约；均为成像/算力层面的经验值）
# --------------------------------------------------------------------------------------

_BASE_LONG_SIDE = 384
"""底分辨率长边上限：连通域分析在小图上做，耗时可控且小噪声尖峰被面积平均抹掉。"""

_MIN_IMAGE_SIDE = 32
"""小于该尺寸的图像没有统计意义，直接拒绝。"""

_SIGMA_BLUR = 3
"""传感器噪声抑制窗口（像素）。"""

_HEAT_THRESHOLD = 0.5
"""底分辨率热力图二值化阈值。定在 0.5：归一化通道里只有占据显著面积的强异常
才能在 INTER_AREA 平均后仍越过 0.5，孤立噪声尖峰被周边像素摊薄到阈值以下。"""

_TOPHAT_SIZES = (3, 5, 9)
"""多尺度 top-hat 核尺寸，分别覆盖点状 / 条状 / 团状缺陷。"""

_CHANNEL_WEIGHTS = (0.50, 0.30, 0.20)
"""res / lc / tex 三通道融合权重（和为 1，结构性残差是主证据）。"""

_NOTCH_SIGMA_RATIO = 0.18
"""陷波宽度（相对基频）= period 的该比例：太窄漏抑制、太宽吃掉缺陷能量。"""

_SEVERITY_COLORS = {
    "high": (60, 60, 235),
    "medium": (0, 170, 255),
    "low": (80, 200, 120),
}


# --------------------------------------------------------------------------------------
# 输入校验与预处理
# --------------------------------------------------------------------------------------


def _validate_and_prepare(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把输入统一成 (原始图, 灰度 float[0,1], 轻平滑灰度 float[0,1])。

    为什么只接受 uint8：上游解码层保证像素量程是 0-255，其他 dtype（float/uint16）
    量程不明，归一化结果不可比，宁可报错也不做隐式缩放。
    """
    if not isinstance(image, np.ndarray):
        raise ValueError("image 必须是 numpy.ndarray")
    if image.dtype != np.uint8:
        raise ValueError(f"image dtype 必须是 uint8，当前为 {image.dtype}")
    if image.ndim == 2:
        gray_u8 = image
    elif image.ndim == 3 and image.shape[2] in (3, 4):
        code = cv2.COLOR_BGR2GRAY if image.shape[2] == 3 else cv2.COLOR_BGRA2GRAY
        gray_u8 = cv2.cvtColor(image, code)
    else:
        raise ValueError(f"image 形状必须是 (H,W)/(H,W,3)/(H,W,4)，当前为 {image.shape}")
    h, w = gray_u8.shape[:2]
    if h == 0 or w == 0 or min(h, w) < _MIN_IMAGE_SIDE:
        raise ValueError(f"图像尺寸过小或为空：{w}x{h}（边长需 ≥ {_MIN_IMAGE_SIDE}）")

    # 轻平滑：高斯噪声会同时抬高残差/梯度两个通道，先 3x3 去噪再算特征；
    # 原始像素保留给叠加图，避免可视化发糊。
    blur_f = cv2.GaussianBlur(gray_u8, (_SIGMA_BLUR, _SIGMA_BLUR), 0).astype(np.float32) / 255.0
    gray_f = gray_u8.astype(np.float32) / 255.0
    return image, gray_f, blur_f


def _percentile_norm(m: np.ndarray, q: float = 99.5) -> np.ndarray:
    """按 99.5 分位归一化到 [0,1]。

    为什么不用 max：单个热像素/坏点会把 max 顶到远超缺陷的水平，压扁其他所有响应；
    分位归一化对离群值稳健，并保留"缺陷应显著高于典型响应"的语义。
    """
    denom = float(np.percentile(m, q)) + 1e-6
    return np.clip(m / denom, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------------------
# 步骤 1：结构化残差通道
# --------------------------------------------------------------------------------------


def _estimate_period(image: np.ndarray, hint: float | None) -> float:
    """估计周期性纹理的空间周期（像素）。0.0 表示"无可用周期"。

    为什么要先估周期再陷波：齿轮/轴承图像里齿纹能量集中在基频+谐波，
    只有拿到周期，陷波才能精确对准，避免误伤宽带缺陷能量。
    用轴向中位数谱（对单行缺陷鲁棒）+ Hann 窗（抑制边缘泄漏）。
    """
    if hint is not None:
        return float(hint)
    h, w = image.shape
    lo, hi = 2.0, float(min(h, w) // 2)
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    spec = cv2.dft((image * win).astype(np.float32), flags=cv2.DFT_COMPLEX_OUTPUT)
    mag = cv2.magnitude(spec[:, :, 0], spec[:, :, 1])
    # 沿行取中位数：竖直条纹在列频率上聚能，中位数对局部缺陷不敏感。
    prof = np.median(mag, axis=0).astype(np.float32)
    u_min = max(1, int(math.ceil(w / hi)))
    u_max = min(w // 2, int(math.floor(w / lo)))
    if u_max <= u_min:
        return 0.0
    band = prof[u_min : u_max + 1]
    u_star = int(np.argmax(band)) + u_min
    period = w / float(u_star)
    if not (lo <= period <= hi):
        return 0.0
    # 显著性检验：谱峰相对中位背景不足 3 倍 → 视为无周期结构，别硬陷波。
    med = float(np.median(band)) + 1e-12
    if float(band.max()) / med < 3.0:
        return 0.0
    return float(period)


def _notch_background(image: np.ndarray, period: float) -> np.ndarray:
    """频域高斯陷波重建"纯纹理背景"（径向环陷波，兼容任意纹理朝向）。

    抑制基频及 ±1、±2 阶谐波所在的频率环：周期纹理能量几乎全部落在这些离散
    频率上，陷掉它们后 idft 得到不含缺陷的结构背景，残差自然只剩缺陷。
    用径向距离做环状陷波，比固定单轴更能应对斜纹/环纹。
    """
    h, w = image.shape
    spec = cv2.dft(image, flags=cv2.DFT_COMPLEX_OUTPUT)
    fk = np.fft.fftfreq(w).astype(np.float32)  # 归一化频率（周/像素）
    fl = np.fft.fftfreq(h).astype(np.float32)
    FK, FL = np.meshgrid(fk, fl)
    fr = np.sqrt(FK * FK + FL * FL)
    f0 = 1.0 / period
    sigma = max(f0 * _NOTCH_SIGMA_RATIO, f0 * 0.02)
    notch = np.ones((h, w), dtype=np.float32)
    for k in (1, 2, 3):
        d = fr - k * f0
        notch = notch * (1.0 - np.exp(-(d * d) / (2.0 * sigma * sigma)))
    filtered = spec * notch[:, :, None]
    recon = cv2.idft(filtered, flags=cv2.DFT_SCALE)
    return cv2.magnitude(recon[:, :, 0], recon[:, :, 1]).astype(np.float32)


def _residual_channel(blur_f: np.ndarray, period: float) -> np.ndarray:
    """结构化残差归一化双向显著图。"""
    if period >= 2.0:
        bg = _notch_background(blur_f, period)
    else:
        # 无周期可陷 → 形态学开运算估计背景：开运算移除比结构核小的亮斑，
        # 残差即"亮于背景的结构外像素"，是通用退化路径。
        k = int(max(9, round(min(blur_f.shape) / 12.0)))
        if k % 2 == 0:
            k += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        bg = cv2.morphologyEx(blur_f, cv2.MORPH_OPEN, kernel)
    res = np.clip(blur_f - bg, -0.5, 0.5)
    # 双向显著：缺陷有亮（异物/反光）也有暗（划伤/气孔），只取单边会漏一半类别。
    res_sig = np.maximum(res, -res)
    return _percentile_norm(res_sig)


# --------------------------------------------------------------------------------------
# 步骤 2：局部对比度通道
# --------------------------------------------------------------------------------------


def _local_contrast(gray_f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """局部相对对比度图 + 大窗局部均值（后者还用于缺陷明暗属性）。

    用相对对比度而非绝对差：光照整体漂移时 gray-loc 会全图抬高造成误报，
    除以 (loc+0.08) 后响应只与"相对邻域的偏离"有关，抗亮度梯度。
    """
    h, w = gray_f.shape
    sigma = max(6.0, min(h, w) / 80.0)
    k = int(sigma * 6.0)
    if k % 2 == 0:
        k += 1
    loc = cv2.GaussianBlur(gray_f, (k, k), sigma)
    lc = np.abs(gray_f - loc) / (loc + 0.08)
    return _percentile_norm(lc), loc


# --------------------------------------------------------------------------------------
# 步骤 3：纹理异常通道
# --------------------------------------------------------------------------------------


def _texture_channel(blur_f: np.ndarray) -> tuple[np.ndarray, float]:
    """梯度偏离显著图 + texture_energy 标量。

    纹理件本身梯度大，"梯度大"不等于缺陷；"梯度异常偏离该图典型梯度"才是。
    用 1.4826*MAD 做稳健标准差：缺陷像素在梯度图里是离群值，普通 std 会被
    缺陷自己拉高、进而把缺陷归一化掉，MAD 对离群不敏感。
    """
    gx = cv2.Sobel(blur_f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur_f, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)
    grad_mean = float(grad.mean())
    mad = float(np.median(np.abs(grad - grad_mean)))
    grad_std = 1.4826 * mad
    tex = np.abs(grad - grad_mean) / (grad_std * 3.0 + 1e-6)
    texture_energy = clamp01(grad_std / 0.25)
    return _percentile_norm(tex), float(texture_energy)


# --------------------------------------------------------------------------------------
# 步骤 4：多尺度形态学增强
# --------------------------------------------------------------------------------------


def _multi_scale_tophat(m: np.ndarray) -> np.ndarray:
    """对 [3,5,9] 椭圆核做 top-hat 取多尺度最大值。

    小核保留细划伤，大核保留团状气孔/压痕；取 max 而不是求和：同一缺陷不应
    因尺度重叠被计两次，求和还会把核尺寸先验引入得分。"""
    out = m.copy()
    for ks in _TOPHAT_SIZES:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks))
        out = np.maximum(out, cv2.morphologyEx(m, cv2.MORPH_TOPHAT, kernel))
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------------------
# 步骤 5：融合 + 结构性抑制
# --------------------------------------------------------------------------------------


def _structure_ratio(heat: np.ndarray) -> tuple[float, int]:
    """投影主频带能量占比（0-1）与条纹主轴标记（0=竖直条纹，1=水平条纹）。

    残差通道对"偏离周期结构"敏感，但齿距变化/相位抖动会在热力图留下与缺陷无关的
    周期性残影；投影 FFT 直接量化"热力图还剩多少周期结构"。"""
    best_ratio = 0.0
    best_axis = 0
    for axis in (0, 1):
        proj = heat.mean(axis=axis)
        proj = proj - float(proj.mean())
        sp = np.abs(np.fft.rfft(proj.astype(np.float64))) ** 2
        if sp.size <= 2:
            continue
        k = int(np.argmax(sp[1:])) + 1
        lo, hi = max(1, k - 1), min(sp.size - 1, k + 1)
        ratio = float(sp[lo : hi + 1].sum() / (sp[1:].sum() + 1e-12))
        if ratio > best_ratio:
            best_ratio = ratio
            best_axis = axis
    return clamp01(best_ratio), best_axis


def _fuse_channels(res_e: np.ndarray, lc_e: np.ndarray, tex_e: np.ndarray) -> tuple[np.ndarray, float]:
    """加权融合并对残余条纹做方向性抑制。

    若结构占比高，把热力图沿"垂直于条纹"方向轻度平滑即得条纹背景，相减后周期残影
    被压掉，而孤立缺陷几乎不受影响（在平滑估计里它权重极小）。"""
    w_res, w_lc, w_tex = _CHANNEL_WEIGHTS
    heat = w_res * res_e + w_lc * lc_e + w_tex * tex_e
    ratio, axis = _structure_ratio(heat)
    if ratio > 0.5:
        k = 9
        blurred = cv2.GaussianBlur(heat, (k, 1) if axis == 0 else (1, k), 0)
        heat = np.clip(heat - blurred, 0.0, 1.0)
    heat = cv2.GaussianBlur(heat.astype(np.float32), (3, 3), 0)
    return np.clip(heat, 0.0, 1.0).astype(np.float32), ratio


# --------------------------------------------------------------------------------------
# 步骤 6：多分辨率连通域
# --------------------------------------------------------------------------------------


def _to_base_map(heat: np.ndarray) -> np.ndarray:
    """把原分辨率热力图缩到底分辨率（长边 ≤ 384）。"""
    h, w = heat.shape[:2]
    scale = _BASE_LONG_SIDE / float(max(h, w))
    if scale >= 1.0:
        return heat.copy()
    return cv2.resize(heat, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)


def _connected_regions(
    norm_map: np.ndarray, cfg: InspectionConfig
) -> tuple[list[tuple[int, RegionStat]], np.ndarray]:
    """二值化 + 连通域标记 + 契约过滤，返回 (候选列表, labels 图)。"""
    binary = cv2.threshold(norm_map, float(_HEAT_THRESHOLD), 1.0, cv2.THRESH_BINARY)[1]
    num, labels, stats, _ = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    candidates: list[tuple[int, RegionStat]] = []
    for rid in range(1, num):
        area = int(stats[rid, cv2.CC_STAT_AREA])
        if area < cfg.min_area_px:  # 先用 CC 面积粗筛，避免对大噪声块做 nonzero
            continue
        rs = region_stats(norm_map, labels, rid, np)
        if rs.peak < cfg.min_peak or rs.area_px < cfg.min_area_px:
            continue
        candidates.append((rid, rs))
    return candidates, labels


# --------------------------------------------------------------------------------------
# 步骤 7：缺陷属性（原分辨率窗口）
# --------------------------------------------------------------------------------------


def _structure_tensor(window: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """结构张量的逐像素 λ1、λ2（2x2 闭式解，无需外部库）。

    λ1/λ2 之比编码"梯度是否有统一主方向"，这是区分划伤（线状）与气孔（点状）的核心证据。"""
    gx = cv2.Sobel(window, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(window, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx * gx, (5, 5), 0)
    jyy = cv2.GaussianBlur(gy * gy, (5, 5), 0)
    jxy = cv2.GaussianBlur(gx * gy, (5, 5), 0)
    tr = jxx + jyy
    det = jxx * jyy - jxy * jxy
    disc = np.sqrt(np.maximum(tr * tr * 0.25 - det, 0.0))
    l1 = np.maximum(tr * 0.5 + disc, 0.0)
    l2 = np.maximum(tr * 0.5 - disc, 0.0)
    return l1, l2, tr


def _region_properties(
    gray_f: np.ndarray,
    loc: np.ndarray,
    mask_orig: np.ndarray,
    rid: int,
    rs: RegionStat,
    scale_x: float,
    scale_y: float,
) -> tuple[float, float, float, float, float]:
    """在原分辨率对应区域窗口内计算 principal_ratio / elongation / circularity / local_std / darkness。"""
    x0, y0, x1, y1 = rs.bbox
    ox0 = max(0, int(x0 * scale_x) - 4)
    oy0 = max(0, int(y0 * scale_y) - 4)
    ox1 = min(gray_f.shape[1], int(x1 * scale_x) + 5)
    oy1 = min(gray_f.shape[0], int(y1 * scale_y) + 5)
    win_mask = (mask_orig[oy0:oy1, ox0:ox1] == rid).astype(np.uint8)
    ys, xs = np.nonzero(win_mask)
    if ys.size == 0:  # 理论不可达（候选面积已过滤 ≥ min_area_px），防御性兜底
        return 0.0, 1.0, 0.0, 0.0, 0.5
    win = gray_f[oy0:oy1, ox0:ox1]
    l1, l2, tr = _structure_tensor(win)
    sel = (ys, xs)
    l1m = float(l1[sel].mean())
    l2m = float(l2[sel].mean())
    trm = float(tr[sel].mean())
    principal_ratio = clamp01((l1m - l2m) / (trm + 1e-6))
    elongation = float(math.sqrt((l1m + 1e-6) / (l2m + 1e-6)))

    contours, _ = cv2.findContours(win_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    circularity = 0.0
    if contours:
        peri = float(max(cv2.arcLength(c, True) for c in contours))
        area = float(win_mask.sum())
        if peri > 1e-6:
            circularity = clamp01(4.0 * math.pi * area / (peri * peri))

    region_gray = win[sel]
    local_std = clamp01(float(region_gray.std()) / 0.35)
    loc_mean = float(loc[oy0:oy1, ox0:ox1][sel].mean())
    region_mean = float(region_gray.mean())
    darkness = clamp01(0.5 + (loc_mean - region_mean) / (loc_mean + 1e-6))
    return principal_ratio, elongation, circularity, local_std, darkness


# --------------------------------------------------------------------------------------
# 步骤 9：叠加可视化
# --------------------------------------------------------------------------------------


def _to_bgr_uint8(image: np.ndarray) -> np.ndarray:
    """任意合法输入 → 三通道 uint8 BGR（叠加渲染用，不修改原图）。"""
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image.copy()


def render_overlay_png(
    image: np.ndarray,
    result: DetectionResult,
    original_heat: np.ndarray | None = None,
) -> str:
    """渲染自包含缺陷叠加图（PNG base64），检测内部与 S3 重渲共用这一实现。

    ``original_heat`` 为底分辨率热力图（与 result.defects[].bbox 同坐标空间）；
    缺省时按同一流水线重算，保证 S3 不重新检测也能重渲。
    """
    _orig, _gray, blur_f = _validate_and_prepare(image)
    base = _to_bgr_uint8(image)
    h, w = base.shape[:2]
    scale = min(1.0, float(MAX_OVERLAY_PX) / float(max(h, w)))
    ow, oh = max(1, int(w * scale)), max(1, int(h * scale))
    if (ow, oh) != (w, h):
        base = cv2.resize(base, (ow, oh), interpolation=cv2.INTER_AREA)

    if original_heat is None:
        profile = SCENE_PROFILES.get(result.scene_id) if result.scene_id is not None else None
        hint = profile.period_hint if profile is not None else None
        heat, _r = DefectDetector._compute_channels(blur_f, hint)
        heat = _to_base_map(heat)
    else:
        heat = np.asarray(original_heat, dtype=np.float32)
    heat_small = cv2.resize(heat, (ow, oh), interpolation=cv2.INTER_LINEAR)
    pseudo = cv2.applyColorMap((heat_small * 255.0).astype(np.uint8), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(base, 0.58, pseudo, 0.42, 0)

    # 缺陷框：bbox 在底分辨率(heat)坐标 → 叠加图坐标 = bbox × (ow/heat_w, oh/heat_h)。
    bh, bw = heat.shape[:2]
    fsx = ow / float(max(1, bw))
    fsy = oh / float(max(1, bh))
    for d in result.defects:
        dx0, dy0, dx1, dy1 = d.bbox
        ox0 = max(0, int(dx0 * fsx))
        oy0 = max(0, int(dy0 * fsy))
        ox1 = min(ow - 1, int((dx1 + 1) * fsx))
        oy1 = min(oh - 1, int((dy1 + 1) * fsy))
        color = _SEVERITY_COLORS.get(d.severity, _SEVERITY_COLORS["low"])
        cv2.rectangle(overlay, (ox0, oy0), (ox1, oy1), color, 1)
        l = max(6, int(min(ox1 - ox0, oy1 - oy0) * 0.25))
        for cx, cy, ddx, ddy in (
            (ox0, oy0, 1, 1), (ox1, oy0, -1, 1), (ox0, oy1, 1, -1), (ox1, oy1, -1, -1)
        ):
            cv2.line(overlay, (cx, cy), (cx + ddx * l, cy), color, 2)
        label = f"{d.defect_id} {d.defect_class} {d.class_confidence:.2f}"
        ty = oy0 - 5 if oy0 > 18 else oy1 + 14
        cv2.putText(overlay, label, (ox0, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    # 左上角半透明信息条：压暗原像素后叠白字。
    text = f"INSPECT-AI | {result.decision.upper()} | score={result.score:.3f} | defects={result.defect_count}"
    bar_h = max(18, oh // 24)
    roi = overlay[0:bar_h]
    cv2.multiply(roi, 0.55, dst=roi)
    cv2.putText(overlay, text, (4, int(bar_h * 0.68)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (240, 240, 240), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", overlay)
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode()


# --------------------------------------------------------------------------------------
# 公开引擎
# --------------------------------------------------------------------------------------


class DefectDetector:
    """无状态检测引擎：参数在构造期绑定，逐图推理互不影响、可并发复用。"""

    def __init__(self, scene_id: str | None = None, config: InspectionConfig | None = None) -> None:
        self._scene_id = scene_id
        self._config = config if config is not None else DEFAULT_CONFIG

    @staticmethod
    def _compute_channels(blur_f: np.ndarray, period_hint: float | None) -> tuple[np.ndarray, float, float, float, np.ndarray]:
        """步骤 1-5：三通道 → 多尺度增强 → 融合与结构性抑制。

        Returns:
            (heat, structure_ratio, texture_energy, period, loc)。
        """
        period = _estimate_period(blur_f, period_hint)
        res_sig = _residual_channel(blur_f, period)
        lc, loc = _local_contrast(blur_f)
        tex, texture_energy = _texture_channel(blur_f)
        heat, structure_ratio = _fuse_channels(
            _multi_scale_tophat(res_sig), _multi_scale_tophat(lc), _multi_scale_tophat(tex)
        )
        return heat, float(structure_ratio), float(texture_energy), float(period), loc

    def inspect(
        self,
        image: np.ndarray,
        image_id: str = "image",
        scene_id: str | None = None,
    ) -> DetectionResult:
        """单图质检入口：输入 uint8 灰度/BGR/BGRA，返回冻结契约的 DetectionResult。"""
        t0 = time.perf_counter()
        _orig, gray_f, blur_f = _validate_and_prepare(image)
        h, w = gray_f.shape[:2]
        scene = scene_id if scene_id is not None else self._scene_id
        profile = SCENE_PROFILES.get(scene) if scene is not None else None
        hint = profile.period_hint if profile is not None else None

        # —— 1-5：通道与融合 ——
        heat, structure_ratio, texture_energy, period, loc = self._compute_channels(blur_f, hint)

        # —— 6：底分辨率连通域 ——
        norm_map = _to_base_map(heat)
        bh, bw = norm_map.shape[:2]
        candidates, labels = _connected_regions(norm_map, self._config)

        # —— 7-8：属性计算、排序、整图融合 ——
        scale_x = gray_f.shape[1] / float(max(1, bw))
        scale_y = gray_f.shape[0] / float(max(1, bh))
        mask_orig = None
        if candidates:
            mask_orig = cv2.resize(labels.astype(np.int32), (gray_f.shape[1], gray_f.shape[0]), interpolation=cv2.INTER_NEAREST)
        defects = self._build_defects(candidates, mask_orig, gray_f, loc, scale_x, scale_y, scene)
        total_area = sum(d.area_px for d in defects)
        max_area = max((d.area_px for d in defects), default=0)

        # 面积零散度：区域面积分布熵归一化。1 个区域 → 0；面积均匀 → 1。
        region_sparsity = 0.0
        if len(defects) > 1:
            areas = np.array([d.area_px for d in defects], dtype=np.float64)
            p = areas / areas.sum()
            ent = float(-(p * np.log(p)).sum())
            region_sparsity = clamp01(ent / math.log(len(defects)))

        clutter = clamp01(structure_ratio * 0.6 + texture_energy * 0.4)
        if structure_ratio > 0.75:
            # 强周期纹理已被残差通道抑制，不该再按杂波惩罚整图得分。
            clutter *= 0.5

        score, breakdown = aggregate_score(total_area, bh * bw, len(defects), max_area, clutter)
        decision = decide(score, self._config)

        result = DetectionResult(
            image_id=image_id,
            scene_id=scene,
            width=int(w),
            height=int(h),
            decision=decision,
            score=float(score),
            processing_ms=float((time.perf_counter() - t0) * 1000.0),
            heatmap_shape=(int(bh), int(bw)),
            defects=defects,
            features={
                "structure_ratio": float(structure_ratio),
                "texture_energy": float(texture_energy),
                "region_sparsity": float(region_sparsity),
                "period": float(period),
            },
            breakdown=breakdown,
        )
        result.overlay_png_b64 = render_overlay_png(image, result, original_heat=norm_map)
        result.processing_ms = float((time.perf_counter() - t0) * 1000.0)
        return result

    def _build_defects(
        self,
        candidates: list[tuple[int, RegionStat]],
        mask_orig: np.ndarray,
        gray_f: np.ndarray,
        loc: np.ndarray,
        scale_x: float,
        scale_y: float,
        scene: str | None,
    ) -> list[DefectItem]:
        """在原分辨率窗口内计算几何/纹理不变量，走契约分类与评分，按得分降序编号。"""
        scored: list[tuple[float, RegionStat, tuple[float, float, float, float, float], tuple[str, float]]] = []
        for rid, rs in candidates:
            principal_ratio, elongation, circularity, local_std, darkness = _region_properties(
                gray_f, loc, mask_orig, rid, rs, scale_x, scale_y
            )
            score = region_score(rs.peak, rs.mean, rs.area_px)
            cls, conf = classify_region(
                rs.peak, principal_ratio, elongation, circularity, local_std, darkness, scene_id=scene
            )
            scored.append((score, rs, (principal_ratio, elongation, circularity, local_std, darkness), (cls, conf)))

        scored.sort(key=lambda t: (-t[0], t[1].region_id))  # 得分降序，同分按 region_id 稳定
        items: list[DefectItem] = []
        for i, (score, rs, feats, (cls, conf)) in enumerate(scored, start=1):
            principal_ratio, elongation, circularity, local_std, darkness = feats
            items.append(
                DefectItem(
                    defect_id=f"D-{i:02d}",
                    defect_class=cls,
                    class_confidence=float(conf),
                    score=float(score),
                    area_px=int(rs.area_px),
                    bbox=(int(rs.bbox[0]), int(rs.bbox[1]), int(rs.bbox[2]), int(rs.bbox[3])),
                    centroid=(float(rs.centroid[0]), float(rs.centroid[1])),
                    severity=score_to_severity(score),
                    features={
                        "peak": float(rs.peak),
                        "mean": float(rs.mean),
                        "principal_ratio": float(principal_ratio),
                        "elongation": float(elongation),
                        "circularity": float(circularity),
                        "local_std": float(local_std),
                        "darkness": float(darkness),
                    },
                )
            )
        return items


@lru_cache(maxsize=8)
def get_detector(scene_id: str | None = None) -> DefectDetector:
    """按场景缓存的引擎单例：避免对同一场景重复构造/绑定配置。"""
    return DefectDetector(scene_id=scene_id)


__all__ = ["DefectDetector", "get_detector", "render_overlay_png"]