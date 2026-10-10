"""`inspectai.contracts` 冻结契约单元测试。

只依赖标准库 + numpy + pytest：禁止 import detectors / generator / api
（这些模块由其他 agent 并行开发中，缺席时本测试仍必须全绿）。
运行：`cd src && python3 -m pytest tests/ -q`
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from inspectai import contracts as c


# --------------------------------------------------------------------------------------
# 配置与校验
# --------------------------------------------------------------------------------------


class TestConfig:
    def test_default_valid(self):
        c.DEFAULT_CONFIG.validate()  # 不应抛异常

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"review_threshold": 0.7, "decision_threshold": 0.6},  # review > decision
            {"decision_threshold": 1.5},                            # decision 越界
            {"review_threshold": 0.0},                              # review 非正
            {"review_threshold": -0.1, "decision_threshold": 0.6},  # review 为负
        ],
    )
    def test_validate_rejects_bad_thresholds(self, kwargs):
        with pytest.raises(ValueError):
            c.InspectionConfig(**kwargs).validate()

    def test_validate_rejects_unnormalized_score_weights(self):
        bad = c.InspectionConfig(
            score_weights={"peak": 0.5, "area": 0.3, "contrast": 0.3}
        )  # 和 = 1.1
        with pytest.raises(ValueError):
            bad.validate()

    def test_validate_rejects_missing_feature_weight(self):
        bad = c.InspectionConfig(feature_weights={"coverage": 1.0})
        with pytest.raises(ValueError):
            bad.validate()

    def test_to_dict(self):
        d = c.DEFAULT_CONFIG.to_dict()
        assert d["decision_threshold"] == c.DEFAULT_CONFIG.decision_threshold
        assert d["score_weights"] == c.DEFAULT_CONFIG.score_weights
        assert d["feature_weights"] == c.DEFAULT_CONFIG.feature_weights


# --------------------------------------------------------------------------------------
# clamp01
# --------------------------------------------------------------------------------------


class TestClamp01:
    def test_nan_to_zero(self):
        assert c.clamp01(float("nan")) == 0.0

    def test_negative(self):
        assert c.clamp01(-3.5) == 0.0
        assert c.clamp01(-1e-12) == 0.0

    def test_over_one(self):
        assert c.clamp01(2.0) == 1.0
        assert c.clamp01(math.inf) == 1.0
        assert c.clamp01(-math.inf) == 0.0

    def test_inside_unchanged(self):
        for x in (0.0, 0.25, 0.5, 1.0):
            assert c.clamp01(x) == x


# --------------------------------------------------------------------------------------
# area_score / count_score
# --------------------------------------------------------------------------------------


class TestSaturation:
    def test_area_score_zero_and_negative(self):
        assert c.area_score(0) == 0.0
        assert c.area_score(-5) == 0.0

    def test_area_score_monotonic(self):
        areas = [0, 1, 5, 20, 100, 500, 2000, 10**6]
        scores = [c.area_score(a) for a in areas]
        assert all(s < t for s, t in zip(scores, scores[1:]))

    def test_area_score_saturates_at_one(self):
        assert c.area_score(10**6) == pytest.approx(1.0, abs=1e-9)

    def test_area_score_default_scale(self):
        assert c.area_score(140) == pytest.approx(1.0 - math.exp(-1.0))

    def test_count_score_zero_and_monotonic(self):
        assert c.count_score(0) == 0.0
        assert c.count_score(-3) == 0.0
        scores = [c.count_score(n) for n in range(11)]
        assert all(s < t for s, t in zip(scores, scores[1:]))
        assert c.count_score(100) == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------------------
# region_score
# --------------------------------------------------------------------------------------


class TestRegionScore:
    def test_all_zero_gives_zero(self):
        assert c.region_score(0.0, 0.0, 0) == 0.0

    def test_strong_defect_above_decision_threshold(self):
        s = c.region_score(1.0, 0.0, 10**6)
        assert s > c.DEFAULT_CONFIG.decision_threshold
        assert 0.0 <= s <= 1.0

    def test_formula_matches_default_weights(self):
        w = c.DEFAULT_CONFIG.score_weights
        expected = c.clamp01(
            w["peak"] * 0.8
            + w["area"] * c.area_score(300)
            + w["contrast"] * c.clamp01((0.8 - 0.3) * 2.0)
        )
        assert c.region_score(0.8, 0.3, 300) == pytest.approx(expected)

    def test_unnormalized_weights_clamp_without_error(self):
        # 实现不做归一化校验：越界得分最终被 clamp01 裁剪到 [0,1]
        w = {"peak": 2.0, "area": 2.0, "contrast": 2.0}
        s = c.region_score(1.0, 0.0, 10**6, weights=w)
        assert s == 1.0  # 0.5+0.3+0.2 项各放大 4 倍后仍被裁剪
        mild = c.region_score(1.0, 1.0, 0, weights={"peak": 0.6, "area": 0.6, "contrast": 0.6})
        assert mild == pytest.approx(0.6)  # 未归一化权重按原样加权后被裁剪


# --------------------------------------------------------------------------------------
# aggregate_score
# --------------------------------------------------------------------------------------


class TestAggregateScore:
    def test_all_zero_gives_zero(self):
        score, breakdown = c.aggregate_score(0, 900 * 1200, 0, 0, 0.0)
        assert score == 0.0
        assert set(breakdown) == {"coverage", "severity", "count", "max_area", "clutter"}
        assert len(breakdown) == 5
        assert all(v == 0.0 for v in breakdown.values())

    def test_breakdown_has_exactly_five_keys(self):
        _, breakdown = c.aggregate_score(5000, 900 * 1200, 3, 800, 0.2)
        assert len(breakdown) == 5

    def test_clutter_adds_linearly_when_core_zero(self):
        w = c.DEFAULT_CONFIG.feature_weights
        score, _ = c.aggregate_score(0, 900 * 1200, 0, 0, 0.5)
        assert score == pytest.approx(w["clutter"] * 0.5)

    def test_score_monotonic_in_total_area(self):
        s1, _ = c.aggregate_score(200, 900 * 1200, 0, 0, 0.0)
        s2, _ = c.aggregate_score(5000, 900 * 1200, 0, 0, 0.0)
        assert 0.0 <= s1 < s2 <= 1.0

    def test_score_clamped_to_one(self):
        score, _ = c.aggregate_score(10**6, 900 * 1200, 50, 10**5, 1.0)
        assert score == 1.0


# --------------------------------------------------------------------------------------
# decide（精确边界，>= 语义）
# --------------------------------------------------------------------------------------


class TestDecide:
    def test_exact_boundaries(self):
        cfg = c.DEFAULT_CONFIG
        assert c.decide(cfg.decision_threshold) == c.DECISION_FAIL      # >= decision
        assert c.decide(cfg.review_threshold) == c.DECISION_REVIEW      # >= review
        assert c.decide(cfg.review_threshold - 1e-9) == c.DECISION_PASS
        assert c.decide(cfg.decision_threshold - 1e-9) == c.DECISION_REVIEW

    def test_extremes(self):
        assert c.decide(0.0) == c.DECISION_PASS
        assert c.decide(1.0) == c.DECISION_FAIL

    def test_custom_config(self):
        cfg = c.InspectionConfig(decision_threshold=0.8, review_threshold=0.5)
        assert c.decide(0.5, cfg) == c.DECISION_REVIEW
        assert c.decide(0.79, cfg) == c.DECISION_REVIEW
        assert c.decide(0.8, cfg) == c.DECISION_FAIL

    def test_score_to_severity_boundaries(self):
        cfg = c.DEFAULT_CONFIG
        assert c.score_to_severity(cfg.decision_threshold) == "high"
        assert c.score_to_severity(cfg.review_threshold) == "medium"
        assert c.score_to_severity(0.1) == "low"


# --------------------------------------------------------------------------------------
# classify_region
# --------------------------------------------------------------------------------------


class TestClassifyRegion:
    def test_scratch(self):
        cls, conf = c.classify_region(
            peak=0.8, principal_ratio=0.95, elongation=8.0, circularity=0.05,
            local_std=0.1, darkness=0.9,
        )
        assert cls == c.CLASS_SCRATCH
        assert 0.05 <= conf <= 1.0

    def test_porosity(self):
        cls, conf = c.classify_region(
            peak=0.6, principal_ratio=0.1, elongation=1.1, circularity=0.95,
            local_std=0.3, darkness=0.5,
        )
        assert cls == c.CLASS_POROSITY
        assert 0.05 <= conf <= 1.0

    def test_indentation(self):
        cls, conf = c.classify_region(
            peak=0.3, principal_ratio=0.1, elongation=1.6, circularity=0.5,
            local_std=0.02, darkness=0.4,
        )
        assert cls == c.CLASS_INDENTATION
        assert 0.05 <= conf <= 1.0

    def test_contamination(self):
        cls, conf = c.classify_region(
            peak=0.9, principal_ratio=0.05, elongation=2.0, circularity=0.1,
            local_std=0.15, darkness=0.1,
        )
        assert cls == c.CLASS_CONTAMINATION
        assert 0.05 <= conf <= 1.0

    def test_no_scene_hard_branching(self):
        # scene_id=None 与未登记场景必须给出完全相同的结果（先验缺席 → 纯形态判断）
        args = dict(
            peak=0.8, principal_ratio=0.95, elongation=8.0, circularity=0.05,
            local_std=0.1, darkness=0.9,
        )
        r_none = c.classify_region(scene_id=None, **args)
        r_unknown = c.classify_region(scene_id="unknown_scene", **args)
        assert r_none == r_unknown

    def test_registered_scene_applies_bounded_prior(self):
        # 登记场景（gear→scratch 先验）与无场景同输入：类别仍可保持，但仅做加权不覆盖证据
        args = dict(
            peak=0.6, principal_ratio=0.8, elongation=6.0, circularity=0.1,
            local_std=0.1, darkness=0.8,
        )
        cls, _ = c.classify_region(scene_id=c.SC_GEAR, **args)
        assert cls == c.CLASS_SCRATCH


# --------------------------------------------------------------------------------------
# 注册表完整性
# --------------------------------------------------------------------------------------


class TestRegistry:
    def test_scene_ids_match_profiles(self):
        assert set(c.SCENE_IDS) == set(c.SCENE_PROFILES.keys())

    def test_scene_profile_ids_consistent(self):
        for scene_id, profile in c.SCENE_PROFILES.items():
            assert profile.scene_id == scene_id
            assert scene_id in c.SCENE_CN

    def test_defect_classes_all_have_cn(self):
        for cls in c.DEFECT_CLASSES:
            assert cls in c.CLASS_CN
        assert c.UNKNOWN_CLASS in c.CLASS_CN

    def test_decision_cn_covers_three(self):
        assert set(c.DECISION_CN) == {
            c.DECISION_PASS,
            c.DECISION_REVIEW,
            c.DECISION_FAIL,
        }

    def test_class_prior_uses_registered_scenes(self):
        for scene_id, (cls, weight) in c.DEFAULT_CONFIG.class_prior_from_scene.items():
            assert scene_id in c.SCENE_IDS
            assert cls in c.DEFECT_CLASSES
            assert 0.0 < weight < 1.0


# --------------------------------------------------------------------------------------
# region_stats（手造 5x5 标记图）
# --------------------------------------------------------------------------------------


class TestRegionStats:
    def test_handcrafted_5x5(self):
        labels = np.zeros((5, 5), dtype=np.int32)
        labels[1:3, 1:3] = 1
        norm_map = np.zeros((5, 5), dtype=np.float32)
        norm_map[1, 1] = 0.2
        norm_map[1, 2] = 0.4
        norm_map[2, 1] = 0.6
        norm_map[2, 2] = 0.8
        stat = c.region_stats(norm_map, labels, 1, np)
        assert stat.region_id == 1
        assert stat.peak == pytest.approx(0.8)
        assert stat.mean == pytest.approx(0.5)
        assert stat.area_px == 4
        assert stat.bbox == (1, 1, 2, 2)
        assert stat.centroid == pytest.approx((1.5, 1.5))


# --------------------------------------------------------------------------------------
# to_dict / JSON 序列化
# --------------------------------------------------------------------------------------


def _make_defect() -> c.DefectItem:
    return c.DefectItem(
        defect_id="d001",
        defect_class=c.CLASS_SCRATCH,
        class_confidence=0.91234,
        score=0.75,
        area_px=120,
        bbox=(10, 20, 30, 40),
        centroid=(25.5, 30.5),
        severity="high",
        features={"elongation": 3.2},
    )


class TestSerialization:
    def test_defect_item_keys(self):
        d = _make_defect().to_dict()
        assert set(d) == {
            "defect_id",
            "defect_class",
            "label_cn",
            "class_confidence",
            "score",
            "area_px",
            "bbox",
            "centroid",
            "severity",
            "features",
        }
        assert d["label_cn"] == c.CLASS_CN[c.CLASS_SCRATCH]
        json.dumps(d)  # 必须可序列化且不抛异常

    def test_detection_result_keys_and_empty_defects(self):
        result = c.DetectionResult(
            image_id="img-1",
            scene_id=c.SC_GEAR,
            width=1200,
            height=900,
            decision=c.DECISION_PASS,
            score=0.1,
            processing_ms=123.456,
            heatmap_shape=(225, 300),
        )
        d = result.to_dict()
        assert set(d) == {
            "contract_version",
            "image_id",
            "scene_id",
            "width",
            "height",
            "decision",
            "label_cn",
            "score",
            "threshold",
            "processing_ms",
            "heatmap_shape",
            "defect_count",
            "defects_by_class",
            "defects",
            "features",
            "breakdown",
            "warnings",
            "overlay_png_b64",
        }
        assert d["defect_count"] == 0
        assert d["defects_by_class"] == {}
        assert d["contract_version"] == c.CONTRACT_VERSION
        json.dumps(d)

    def test_detection_result_with_defects_roundtrip(self):
        result = c.DetectionResult(
            image_id="img-2",
            scene_id=None,
            width=1200,
            height=900,
            decision=c.DECISION_FAIL,
            score=0.8,
            processing_ms=99.9,
            heatmap_shape=(225, 300),
            defects=[_make_defect(), _make_defect()],
            features={"clutter_ratio": 0.1},
            breakdown={"coverage": 0.2},
            warnings=["低分辨率"],
            overlay_png_b64="AAAA",
        )
        d = result.to_dict()
        assert d["defect_count"] == 2
        assert d["defects_by_class"] == {c.CLASS_SCRATCH: 2}
        assert d["label_cn"] == c.DECISION_CN[c.DECISION_FAIL]
        text = json.dumps(d, ensure_ascii=False)
        assert "线性划伤" in text
