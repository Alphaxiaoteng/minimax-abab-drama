"""跨模块不可变契约（Cross-module frozen contract）。

本文件是 S1/S2/S3/S4 并行开发的唯一接口来源，任何模块都不得修改此文件的数据结构，
只能消费。修改契约必须先回到架构层评审。

关键约定
--------
* 检测流水线输出 ``float32``、范围 ``[0, 1]``、形状 ``(H, W)`` 的 **缺陷得分热力图**；
  ``0`` 表示合格，``1`` 表示确定性缺陷。
* 所有像素坐标使用 ``(x, y)``＝``(列, 行)``，左上角为原点，坐标为 **像素整数**。
* 所有判定阈值集中在 :data:`DEFAULT_CONFIG`，禁止在算法内部散落魔法数字。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------------------
# 版本
# --------------------------------------------------------------------------------------

CONTRACT_VERSION = "1.0.0"
"""供 S3 在 ``/api/v1/health`` 中回显，便于前后端联调时确认契约版本一致。"""

# --------------------------------------------------------------------------------------
# 缺陷类别
# --------------------------------------------------------------------------------------

CLASS_SCRATCH = "scratch"
CLASS_POROSITY = "porosity"
CLASS_INDENTATION = "indentation"
CLASS_CONTAMINATION = "contamination"
UNKNOWN_CLASS = "unknown"

DEFECT_CLASSES: tuple[str, ...] = (
    CLASS_SCRATCH,
    CLASS_POROSITY,
    CLASS_INDENTATION,
    CLASS_CONTAMINATION,
)
"""S2 生成数据集与 S1 分类器共同遵守的标签空间（4 类）。"""

CLASS_CN: dict[str, str] = {
    CLASS_SCRATCH: "线性划伤",
    CLASS_POROSITY: "气孔砂眼",
    CLASS_INDENTATION: "压痕磕碰",
    CLASS_CONTAMINATION: "油污异物",
    UNKNOWN_CLASS: "未分类缺陷",
}

# --------------------------------------------------------------------------------------
# 质检场景（长江三角工业质检四大典型件）
# --------------------------------------------------------------------------------------

SC_GEAR = "gear_surface"
SC_BEARING = "bearing_ring"
SC_CASTING = "casting_cover"
SC_STAMPING = "stamping_shell"

SCENE_IDS: tuple[str, ...] = (SC_GEAR, SC_BEARING, SC_CASTING, SC_STAMPING)

SCENE_CN: dict[str, str] = {
    SC_GEAR: "齿轮齿面 · 划伤检测",
    SC_BEARING: "轴承套圈 · 滚道点蚀",
    SC_CASTING: "铝合金压铸件 · 气孔砂眼",
    SC_STAMPING: "冲压覆盖件 · 压痕油污",
}


@dataclass(frozen=True)
class SceneProfile:
    """一个质检工位的成像与工艺先验。

    检测引擎内部的参数自适应（结构周期估计、梯度基线、纹理不变量）全部由本结构
    以及图像自身的统计量驱动，**不依赖** :data:`SCENE_IDS` 的枚举值。
    因此未登记的新场景可通过 ``custom`` profile 直接接入。

    Attributes:
        scene_id: 场景标识，见 :data:`SCENE_IDS`。
        part_name: 中文工件名。
        period_hint: 结构性纹理的预期空间周期（像素）；``None`` 表示由频谱峰值自动估计。
        gradient_prior: 纹理梯度能量的先验（归一化），用于评估阶段诊断。
        seed: 生成该场景图像时使用的随机种子（仅 S2 使用）。
        background: 背景基色 ``(g, g, g)`` 灰度值。
        defect_scale: 各类缺陷的相对尺寸缩放。
    """

    scene_id: str
    part_name: str
    period_hint: float | None
    gradient_prior: float
    seed: int
    background: int
    defect_scale: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "part_name": self.part_name,
            "period_hint": self.period_hint,
            "gradient_prior": self.gradient_prior,
            "background": self.background,
            "defect_scale": self.defect_scale,
        }


SCENE_PROFILES: dict[str, SceneProfile] = {
    SC_GEAR: SceneProfile(
        scene_id=SC_GEAR,
        part_name="齿轮齿面",
        period_hint=9.0,
        gradient_prior=0.060,
        seed=20261001,
        background=118,
        defect_scale=1.0,
    ),
    SC_BEARING: SceneProfile(
        scene_id=SC_BEARING,
        part_name="轴承套圈",
        period_hint=18.0,
        gradient_prior=0.045,
        seed=20261002,
        background=142,
        defect_scale=0.8,
    ),
    SC_CASTING: SceneProfile(
        scene_id=SC_CASTING,
        part_name="铝合金压铸件",
        period_hint=None,
        gradient_prior=0.022,
        seed=20261003,
        background=166,
        defect_scale=1.15,
    ),
    SC_STAMPING: SceneProfile(
        scene_id=SC_STAMPING,
        part_name="冲压覆盖件",
        period_hint=34.0,
        gradient_prior=0.018,
        seed=20261004,
        background=178,
        defect_scale=1.3,
    ),
}


# --------------------------------------------------------------------------------------
# 检测结果数据模型
# --------------------------------------------------------------------------------------


@dataclass
class DefectItem:
    """Heatmap 中一个连通缺陷区域的量化描述。"""

    defect_id: str
    defect_class: str
    class_confidence: float
    score: float
    area_px: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]
    severity: str
    features: dict[str, float] = field(default_factory=dict)

    @property
    def label_cn(self) -> str:
        return CLASS_CN.get(self.defect_class, CLASS_CN[UNKNOWN_CLASS])

    @property
    def bbox_xyxy(self) -> tuple[int, int, int, int]:
        return self.bbox

    def to_dict(self) -> dict[str, Any]:
        return {
            "defect_id": self.defect_id,
            "defect_class": self.defect_class,
            "label_cn": self.label_cn,
            "class_confidence": round(float(self.class_confidence), 4),
            "score": round(float(self.score), 4),
            "area_px": int(self.area_px),
            "bbox": [int(v) for v in self.bbox],
            "centroid": [round(float(self.centroid[0]), 2), round(float(self.centroid[1]), 2)],
            "severity": self.severity,
            "features": {k: round(float(v), 4) for k, v in self.features.items()},
        }


@dataclass
class DetectionResult:
    """一次完整质检的产出。S3 的 ``/api/v1/inspect`` 直接序列化本对象。"""

    image_id: str
    scene_id: str | None
    width: int
    height: int
    decision: str
    score: float
    processing_ms: float
    heatmap_shape: tuple[int, int]
    defects: list[DefectItem] = field(default_factory=list)
    features: dict[str, float] = field(default_factory=dict)
    breakdown: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    overlay_png_b64: str | None = None
    contract_version: str = CONTRACT_VERSION

    @property
    def defect_count(self) -> int:
        return len(self.defects)

    @property
    def defects_by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.defects:
            counts[item.defect_class] = counts.get(item.defect_class, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "image_id": self.image_id,
            "scene_id": self.scene_id,
            "width": int(self.width),
            "height": int(self.height),
            "decision": self.decision,
            "label_cn": DECISION_CN.get(self.decision, self.decision),
            "score": round(float(self.score), 4),
            "threshold": DEFAULT_CONFIG.decision_threshold,
            "processing_ms": round(float(self.processing_ms), 2),
            "heatmap_shape": [int(self.heatmap_shape[0]), int(self.heatmap_shape[1])],
            "defect_count": self.defect_count,
            "defects_by_class": self.defects_by_class,
            "defects": [d.to_dict() for d in self.defects],
            "features": {k: round(float(v), 4) for k, v in self.features.items()},
            "breakdown": {k: round(float(v), 4) for k, v in self.breakdown.items()},
            "warnings": list(self.warnings),
            "overlay_png_b64": self.overlay_png_b64,
        }


# --------------------------------------------------------------------------------------
# 判定标签
# --------------------------------------------------------------------------------------

DECISION_PASS = "pass"
DECISION_REVIEW = "review"
DECISION_FAIL = "fail"

DECISION_CN: dict[str, str] = {
    DECISION_PASS: "合格 · 放行",
    DECISION_REVIEW: "可疑 · 人工复检",
    DECISION_FAIL: "不合格 · 拦截",
}


# --------------------------------------------------------------------------------------
# 区域统计元组契约
# --------------------------------------------------------------------------------------




@dataclass(frozen=True)
class RegionStat:
    """一个候选区域的原始统计量。

    由 :func:`inspectai.contracts.region_stats` 在**底分辨率特征图**上计算，
    是 :func:`inspectai.contracts.region_score` 的唯一输入。
    """

    region_id: int
    peak: float
    mean: float
    area_px: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]


def region_stats(
    norm_map: "Any",
    labels: "Any",
    region_id: int,
    np: "Any",
) -> RegionStat:
    """从 ``labels`` 中提取第 ``region_id`` 号区域的统计量。

    Args:
        norm_map: ``float32 (h, w)`` 归一化置信图，范围 ``[0, 1]``。
        labels: ``int32 (h, w)`` 连通域标记图（0 为背景）。
        region_id: 目标区域编号，从 1 开始。
        np: 已 import 的 numpy 模块（避免本模块在 import 期依赖 numpy）。

    Returns:
        :class:`RegionStat`。
    """
    ys, xs = np.nonzero(labels == region_id)
    values = norm_map[ys, xs]
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return RegionStat(
        region_id=int(region_id),
        peak=float(values.max()),
        mean=float(values.mean()),
        area_px=int(values.size),
        bbox=bbox,
        centroid=(float(xs.mean()), float(ys.mean())),
    )


# --------------------------------------------------------------------------------------
# 全局配置与评分权重
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InspectionConfig:
    """全套阈值与权重。

    所有字段都被 :class:`~inspectai.scoring.Scorer`、检测引擎与 Web 端下拉框共用；
    S3 的 ``/api/v1/config`` 会原样暴露本结构，S4 不允许硬编码任何阈值。

    Attributes:
        decision_threshold: 整图融合得分 ≥ 该值判为 ``fail``。
        review_threshold: 整图融合得分 ≥ 该值（且 < ``decision_threshold``）判为 ``review``。
        min_peak: 候选区域热力图峰值下限，低于该值的噪声区域直接丢弃。
        min_area_px: 底分辨率特征图上的最小有效缺陷面积（像素）。
        score_weights: 单区域得分 = Σ w_k · s_k，必须归一化（和为 1）。
        feature_weights: 整图融合得分；``coverage`` 与 ``severity`` 互斥使用，
            其余为独立加分项，最终以 ``max`` 聚合后裁剪到 ``[0, 1]``。
        class_prior_from_scene: 场景→主导缺陷类别的先验（弱先验，仅加权，不覆盖视觉证据）。
    """

    decision_threshold: float = 0.62
    review_threshold: float = 0.42
    min_peak: float = 0.15
    min_area_px: int = 6
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "peak": 0.50,
            "area": 0.30,
            "contrast": 0.20,
        }
    )
    feature_weights: dict[str, float] = field(
        default_factory=lambda: {
            "coverage": 1.00,
            "severity": 0.92,
            "count": 0.85,
            "max_area": 0.80,
            "clutter": 0.40,
        }
    )
    class_prior_from_scene: dict[str, tuple[str, float]] = field(
        default_factory=lambda: {
            SC_GEAR: (CLASS_SCRATCH, 0.18),
            SC_BEARING: (CLASS_POROSITY, 0.18),
            SC_CASTING: (CLASS_POROSITY, 0.20),
            SC_STAMPING: (CLASS_INDENTATION, 0.16),
        }
    )

    def validate(self) -> None:
        if not 0.0 < self.review_threshold <= self.decision_threshold <= 1.0:
            raise ValueError("review_threshold 必须 ∈ (0, decision_threshold]")
        total = sum(self.score_weights.values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"score_weights 必须归一化，当前和={total}")
        for key in ("coverage", "severity", "count", "max_area", "clutter"):
            if key not in self.feature_weights:
                raise ValueError(f"feature_weights 缺少聚合项 {key!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_threshold": self.decision_threshold,
            "review_threshold": self.review_threshold,
            "min_peak": self.min_peak,
            "min_area_px": self.min_area_px,
            "score_weights": dict(self.score_weights),
            "feature_weights": dict(self.feature_weights),
        }


DEFAULT_CONFIG = InspectionConfig()
DEFAULT_CONFIG.validate()

MAX_OVERLAY_PX = 900
"""叠加图最长边上限，避免响应体过大；S1 负责缩放，S3 只透传。"""


# --------------------------------------------------------------------------------------
# 纯函数评分契约（S1 与离线评估脚本共用，必须保持一致）
# --------------------------------------------------------------------------------------


def clamp01(x: float) -> float:
    """裁剪到 ``[0, 1]``，``NaN`` 归零。"""
    if x != x:  # NaN
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def area_score(area_px: int, scale_px: float = 140.0) -> float:
    """面积饱和函数：``1 - exp(-area / scale)``，无上界裁剪问题。"""
    if area_px <= 0:
        return 0.0
    return clamp01(1.0 - math.exp(-float(area_px) / float(scale_px)))


def score_to_severity(score: float) -> str:
    """按单区域得分映射严重度；阈值与 :data:`DEFAULT_CONFIG` 同源。"""
    cfg = DEFAULT_CONFIG
    if score >= cfg.decision_threshold:
        return "high"
    if score >= cfg.review_threshold:
        return "medium"
    return "low"


def region_score(
    peak: float,
    mean: float,
    area_px: int,
    area_scale_px: float = 140.0,
    weights: dict[str, float] | None = None,
) -> float:
    """单缺陷区域融合得分 ∈ ``[0, 1]``。

    ``score = w_peak·peak + w_area·area_score(area) + w_contrast·(peak - mean)·2``

    Args:
        peak: 区域热力图峰值 ∈ ``[0, 1]``。
        mean: 区域热力图均值 ∈ ``[0, 1]``。
        area_px: 区域像素面积（热力图分辨率）。
        area_scale_px: 面积饱和尺度。
        weights: 权重，默认取 :data:`DEFAULT_CONFIG`。

    Returns:
        融合得分，越大越严重。
    """
    w = weights or DEFAULT_CONFIG.score_weights
    peak = clamp01(peak)
    mean = clamp01(mean)
    contrast = clamp01((peak - mean) * 2.0)
    return clamp01(
        w["peak"] * peak
        + w["area"] * area_score(area_px, area_scale_px)
        + w["contrast"] * contrast
    )


def count_score(n: int, scale: float = 3.0) -> float:
    """缺陷数量饱和项。"""
    if n <= 0:
        return 0.0
    return clamp01(1.0 - math.exp(-float(n) / float(scale)))


def aggregate_score(
    total_area_px: int,
    image_px: int,
    n_defects: int,
    max_area_px: int,
    clutter_ratio: float,
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """整图融合得分。

    ``score = max(coverage, severity, count, max_area) + w_clutter·clutter``，
    其中 ``coverage = 1 - exp(-total_area / (image_px·0.04))``。

    Args:
        total_area_px: 全部有效缺陷面积之和（热力图分辨率）。
        image_px: 热力图总像素数。
        n_defects: 有效缺陷个数。
        max_area_px: 单缺陷最大面积。
        clutter_ratio: 纹理杂波比 ∈ ``[0, 1]``（由检测引擎给出，见 S1）。
        weights: 默认 :data:`DEFAULT_CONFIG`。

    Returns:
        ``(score, breakdown)``，``breakdown`` 为各项分量的原始值，便于 Web 端展示归因。
    """
    w = weights or DEFAULT_CONFIG.feature_weights
    coverage = clamp01(1.0 - math.exp(-float(total_area_px) / max(1.0, float(image_px) * 0.04)))
    severity = clamp01(area_score(max_area_px, 260.0))
    cnt = count_score(n_defects)
    max_area = clamp01(area_score(max_area_px, 140.0))
    clutter = clamp01(clutter_ratio)
    core = max(coverage, severity, cnt, max_area)
    breakdown = {
        "coverage": coverage,
        "severity": severity,
        "count": cnt,
        "max_area": max_area,
        "clutter": clutter,
    }
    return clamp01(core + w["clutter"] * clutter), breakdown


def decide(score: float, cfg: InspectionConfig | None = None) -> str:
    """得分 → :data:`DECISION_PASS` / :data:`DECISION_REVIEW` / :data:`DECISION_FAIL`。"""
    cfg = cfg or DEFAULT_CONFIG
    if score >= cfg.decision_threshold:
        return DECISION_FAIL
    if score >= cfg.review_threshold:
        return DECISION_REVIEW
    return DECISION_PASS


def classify_region(
    peak: float,
    principal_ratio: float,
    elongation: float,
    circularity: float,
    local_std: float,
    darkness: float,
    scene_id: str | None = None,
    scene_prior_weight: float | None = None,
) -> tuple[str, float]:
    """基于几何与纹理不变量把区域映射到 :data:`DEFECT_CLASSES`。

    设计原则：**不使用场景硬分支**。先由形态学证据给出类别，再把场景先验作为
    有界加权（不超过 ``scene_prior_weight``），从而对未登记场景自动降级为纯形态判断。

    Args:
        peak: 区域峰值 ∈ ``[0, 1]``。
        principal_ratio: 主轴方向结构能量 / 总结构能量 ∈ ``[0, 1]``，越大越"线状"。
        elongation: 主轴长度 / 短轴长度，≥ 1。
        circularity: ``4πA/P²`` ∈ ``[0, 1]``，越大越"圆"。
        local_std: 区域内灰度标准差（归一化到 ``[0, 1]``）。
        darkness: 暗向显著性 ∈ ``[0, 1]``，1 表示完全暗于邻域。
        scene_id: 场景标识；``None`` 或未登记则不加先验。
        scene_prior_weight: 覆盖 :data:`DEFAULT_CONFIG.class_prior_from_scene` 的权重。

    Returns:
        ``(defect_class, confidence)``，``confidence`` 为归一化类别置信度 ∈ ``[0.05, 1]``。
    """
    cfg = DEFAULT_CONFIG
    elongation = max(1.0, float(elongation))
    circularity = clamp01(circularity)
    principal_ratio = clamp01(principal_ratio)
    local_std = clamp01(local_std)
    darkness = clamp01(darkness)

    # 1) 线状划伤：强主方向 + 细长 + 低圆度，且局部对比度较高
    scratch = clamp01(
        0.55 * principal_ratio
        + 0.30 * min(1.0, (elongation - 1.4) / 6.0)
        + 0.15 * (1.0 - circularity)
    ) * (0.6 + 0.4 * darkness)

    # 2) 气孔砂眼：高圆度、面积中等、局部灰度方差大（多孔）
    pore = clamp01(
        0.45 * circularity
        + 0.30 * min(1.0, local_std / 0.22)
        + 0.25 * (1.0 - min(1.0, (elongation - 1.4) / 4.0))
    )

    # 3) 压痕磕碰：大而弥散、低峰值、中低圆度、低局部方差
    dent = clamp01(
        0.40 * (1.0 - peak) * min(1.0, elongation / 2.0)
        + 0.35 * (1.0 - min(1.0, local_std / 0.20))
        + 0.25 * (0.5 * (1.0 - principal_ratio) + 0.5 * (1.0 - circularity))
    )

    # 4) 油污异物：高对比但低结构、形状不规则
    smear = clamp01(
        0.45 * (1.0 - principal_ratio)
        + 0.30 * (1.0 - circularity)
        + 0.25 * peak
    ) * (0.7 + 0.3 * (1.0 - darkness))

    raw = {
        CLASS_SCRATCH: scratch,
        CLASS_POROSITY: pore,
        CLASS_INDENTATION: dent,
        CLASS_CONTAMINATION: smear,
    }

    prior = cfg.class_prior_from_scene.get(scene_id or "")
    if prior is not None:
        p_class, p_w = prior
        weight = scene_prior_weight if scene_prior_weight is not None else p_w
        raw[p_class] = clamp01(raw[p_class] + float(weight))

    ordered = sorted(raw.items(), key=lambda kv: kv[1], reverse=True)
    best_class, best = ordered[0]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0.0
    if best <= 1e-6:
        return UNKNOWN_CLASS, 0.05
    margin = clamp01((best - runner_up) / max(best, 1e-6))
    confidence = clamp01(0.35 + 0.65 * (0.5 * best + 0.5 * margin))
    return best_class, max(0.05, confidence)


__all__ = [
    "CONTRACT_VERSION",
    "MAX_OVERLAY_PX",
    "CLASS_SCRATCH",
    "CLASS_POROSITY",
    "CLASS_INDENTATION",
    "CLASS_CONTAMINATION",
    "UNKNOWN_CLASS",
    "DEFECT_CLASSES",
    "CLASS_CN",
    "SCENE_IDS",
    "SCENE_CN",
    "SCENE_PROFILES",
    "SceneProfile",
    "DefectItem",
    "DetectionResult",
    "RegionStat",
    "DECISION_PASS",
    "DECISION_REVIEW",
    "DECISION_FAIL",
    "DECISION_CN",
    "InspectionConfig",
    "DEFAULT_CONFIG",
    "region_stats",
    "clamp01",
    "area_score",
    "score_to_severity",
    "region_score",
    "count_score",
    "aggregate_score",
    "decide",
    "classify_region",
]
