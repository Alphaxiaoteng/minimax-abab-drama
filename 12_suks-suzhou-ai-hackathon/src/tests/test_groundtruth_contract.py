"""`inspectai.domain.groundtruth` 真值契约测试。

Annotation / GroundTruth 由其他 agent（DatasetLab）并行提供：
模块或符号缺席时整体**跳过**而非失败。只依赖标准库 + pytest。
运行：`cd src && python3 -m pytest tests/ -q`
"""
from __future__ import annotations

import pytest

gt = pytest.importorskip(
    "inspectai.domain.groundtruth",
    reason="groundtruth.py 尚未就绪（由 S2 agent 并行开发），跳过真值契约测试",
)

if not (hasattr(gt, "Annotation") and hasattr(gt, "GroundTruth")):
    pytest.skip(
        "groundtruth 模块暂无 Annotation/GroundTruth 符号（S2 并行开发中），跳过",
        allow_module_level=True,
    )

Annotation = gt.Annotation
GroundTruth = gt.GroundTruth


def _sample_annotations():
    return [
        Annotation(
            defect_class="scratch",
            bbox=(10, 20, 100, 8),
            score=0.7,
            features={"length": 100.0, "width": 8.0, "depth": 0.3, "contrast": 0.55},
        ),
        Annotation(
            defect_class="porosity",
            bbox=(50, 60, 12, 12),
            score=0.45,
            features={"length": 12.0, "width": 12.0, "depth": 0.2, "contrast": 0.6},
        ),
    ]


class TestAnnotationRoundtrip:
    def test_to_dict_keys(self):
        d = Annotation(
            defect_class="scratch",
            bbox=(1, 2, 3, 4),
            score=0.5,
            features={"length": 3.0, "width": 1.0, "depth": 0.1, "contrast": 0.2},
        ).to_dict()
        assert set(d) == {"defect_class", "bbox", "score", "features"}
        assert d["bbox"] == [1, 2, 3, 4]

    def test_roundtrip(self):
        for ann in _sample_annotations():
            restored = Annotation.from_dict(ann.to_dict())
            assert restored == ann

    def test_from_dict_defaults_features(self):
        ann = Annotation.from_dict(
            {"defect_class": "contamination", "bbox": [0, 0, 5, 5], "score": 0.2}
        )
        assert ann.features == {}


class TestGroundTruthRoundtrip:
    def test_roundtrip_with_defects(self):
        truth = GroundTruth(
            image_id="img-ng-001",
            scene_id="gear_surface",
            image_path="data/img-ng-001.png",
            annotations=_sample_annotations(),
        )
        restored = GroundTruth.from_dict(truth.to_dict())
        assert restored == truth
        assert restored.is_defective is True

    def test_roundtrip_ok_image(self):
        truth = GroundTruth(
            image_id="img-ok-001",
            scene_id="bearing_ring",
            image_path="data/img-ok-001.png",
            annotations=[],
        )
        restored = GroundTruth.from_dict(truth.to_dict())
        assert restored == truth
        assert restored.is_defective is False

    def test_is_defective_counts_annotations(self):
        truth = GroundTruth(
            image_id="img-1", scene_id="casting_cover", image_path="p.png"
        )
        assert truth.is_defective is False
        truth.annotations.append(_sample_annotations()[0])
        assert truth.is_defective is True


class TestManifestRoundtrip:
    def test_write_read_manifest(self, tmp_path):
        if not (hasattr(gt, "write_manifest") and hasattr(gt, "read_manifest")):
            pytest.skip("groundtruth 模块暂无 manifest 读写函数（S2 并行开发中），跳过")
        truths = [
            GroundTruth(
                image_id="a", scene_id="gear_surface",
                image_path="data/a.png", annotations=_sample_annotations(),
            ),
            GroundTruth(
                image_id="b", scene_id="stamping_shell",
                image_path="data/b.png", annotations=[],
            ),
        ]
        path = str(tmp_path / "manifest.json")
        gt.write_manifest(truths, path)
        loaded = gt.read_manifest(path)
        assert loaded == truths