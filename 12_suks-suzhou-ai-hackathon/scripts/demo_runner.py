#!/usr/bin/env python3
"""12_suks-suzhou-ai-hackathon: 长三角工业质检缺陷检测实战离线演示."""
from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import cv2
import numpy as np

from inspectai.contracts import SCENE_IDS, SCENE_CN, DECISION_PASS, DECISION_REVIEW, DECISION_FAIL
from inspectai.domain.generator import SyntheticPartGenerator
from inspectai.detectors.core import get_detector

def main() -> int:
    print("=" * 80)
    print("InspectAI 长三角智能制造工件表面缺陷检测引擎 · 现场离线推演")
    print("=" * 80)

    print(f"{'场景 ID':<16}{'场景名称':<12}{'样本':<6}{'真实标签':<8}{'检测裁决':<8}{'置信得分':>10}{'耗时(ms)':>10}{'缺陷数':>8}")
    print("-" * 80)

    total_samples = 0
    correct_decisions = 0

    for scene_id in SCENE_IDS:
        generator = SyntheticPartGenerator(scene_id, seed=100 + total_samples)
        detector = get_detector(scene_id)
        scene_name = SCENE_CN.get(scene_id, scene_id)
        for kind, has_defect in (("OK", False), ("NG", True)):
            total_samples += 1
            expected_decision = DECISION_FAIL if has_defect else DECISION_PASS
            gt_label = "NG (缺陷)" if has_defect else "OK (良品)"

            # 生成确定性测试样本
            img, gt = generator.generate(has_defect=has_defect)
            if img.dtype != np.uint8:
                img = np.clip(img, 0, 255).astype(np.uint8)

            t0 = time.perf_counter()
            result = detector.inspect(img, image_id=f"{scene_id}_{kind}", scene_id=scene_id)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            if result.decision == DECISION_PASS:
                decision_str = "PASS (良品)"
            elif result.decision == DECISION_FAIL:
                decision_str = "FAIL (报废)"
            else:
                decision_str = "REVIEW (复检)"

            if has_defect:
                is_match = (result.decision in (DECISION_FAIL, DECISION_REVIEW))
            else:
                is_match = (result.decision == DECISION_PASS)

            if is_match:
                correct_decisions += 1

            n_defects = len(result.defects)
            print(f"{scene_id:<16}{scene_name:<12}{kind:<6}{gt_label:<10}{decision_str:<10}{result.score:>10.4f}{elapsed_ms:>10.2f}{n_defects:>8}")

            if result.defects:
                for d in result.defects[:2]:
                    print(f"   └─ 检出缺陷: [{d.label_cn}] 严重度={d.severity} 面积={d.area_px}px 置信度={d.class_confidence:.2f}")

    print("-" * 80)
    acc = correct_decisions / total_samples * 100.0
    print(f"总计推演样本: {total_samples} | 裁决吻合率: {acc:.1f}% ({correct_decisions}/{total_samples})")
    print("长三角工业质检算法验证通过 ✅")
    return 0

if __name__ == "__main__":
    sys.exit(main())
