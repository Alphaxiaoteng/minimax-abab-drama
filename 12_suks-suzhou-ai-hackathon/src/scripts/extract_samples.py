"""离线样例图提取脚本（Web 工作台演示用）。

给 S4 前端准备**确定性**离线样例图，避免 Demo 现场依赖随机生成：
对 ``SCENE_IDS`` 的每个场景，用合成生成器落盘 ``--per-scene`` 张 OK 与
``--per-scene`` 张 NG 图，并写出 ``index.json`` 清单（每图含
``scene_id`` / ``has_defect`` / ``label_cn`` / ``ground_truth`` 摘要）。

用法::

    cd src
    python3 scripts/extract_samples.py --out service/static/samples --per-scene 3

生成器 ``inspectai.domain.generator`` 由 S2 agent 并行开发；本脚本对其
**惰性 import**，缺席时打印中文提示并以退出码 1 结束（不抛栈）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inspectai.contracts import (  # noqa: E402  (路径注入后再 import)
    DECISION_CN,
    DECISION_FAIL,
    DECISION_PASS,
    SCENE_CN,
    SCENE_IDS,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="extract_samples.py",
        description="为 Web 工作台生成确定性的离线样例图（OK/NG PNG + index.json 清单）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--out",
        default="service/static/samples",
        help="样例图输出目录（相对当前工作目录）",
    )
    parser.add_argument(
        "--per-scene",
        type=int,
        default=3,
        help="每个场景生成的 OK 与 NG 图各多少张",
    )
    return parser.parse_args()


def _ground_truth_summary(gt_obj: Any) -> dict[str, Any]:
    """把 GroundTruth 压缩成 index.json 里的摘要条目。"""
    annotations = getattr(gt_obj, "annotations", []) or []
    return {
        "n_defects": len(annotations),
        "classes": [getattr(a, "defect_class", "unknown") for a in annotations],
        "bboxes": [list(getattr(a, "bbox", (0, 0, 0, 0))) for a in annotations],
    }


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    """统一转 uint8，保证 cv2.imwrite 可写。"""
    if arr.dtype == np.uint8:
        return arr
    return np.clip(arr, 0, 255).astype(np.uint8)


def main() -> int:
    args = parse_args()
    if args.per_scene < 1:
        print("错误：--per-scene 必须 ≥ 1")
        return 1

    try:
        from inspectai.domain.generator import SyntheticPartGenerator
    except ImportError:
        print(
            "错误：未找到合成图像生成器 inspectai.domain.generator.SyntheticPartGenerator，\n"
            "该模块由数据集 agent（S2）并行开发中，请先完成 src/inspectai/domain/generator.py "
            "后再运行本脚本。"
        )
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    for scene_id in SCENE_IDS:
        generator = SyntheticPartGenerator(scene_id)
        for kind, has_defect in (("ok", False), ("ng", True)):
            for i in range(args.per_scene):
                arr, gt_obj = generator.generate(has_defect=has_defect)
                filename = f"{scene_id}_{kind}_{i:02d}.png"
                if not cv2.imwrite(str(out_dir / filename), _to_uint8(arr)):
                    print(f"错误：无法写入 {out_dir / filename}")
                    return 1
                items.append(
                    {
                        "file": filename,
                        "scene_id": scene_id,
                        "scene_cn": SCENE_CN.get(scene_id, scene_id),
                        "has_defect": has_defect,
                        "label_cn": DECISION_CN[
                            DECISION_FAIL if has_defect else DECISION_PASS
                        ],
                        "ground_truth": _ground_truth_summary(gt_obj),
                    }
                )
                print(f"已生成 {filename}")

    index_path = out_dir / "index.json"
    payload = {"n_images": len(items), "images": items}
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"完成：{len(items)} 张样例图 + 清单 → {index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())