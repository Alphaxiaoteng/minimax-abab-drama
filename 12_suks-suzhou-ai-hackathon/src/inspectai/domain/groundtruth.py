"""合成数据集真值契约（S2 生成器 / 检测器 / S3 评测共用）。

本模块是 **共享契约**：``generator.py`` 写入 manifest，评测脚本与 Web 展示读取，
三方都只依赖这里冻结的数据结构与判定口径，禁止在其他模块复制粘贴这些逻辑。

判定口径
--------
* **图像级**：有 ≥1 条 annotation 视为缺陷图（ground truth 阳性）；
  ``decision != "pass"`` 视为报警。缺陷图被报警 → TP；缺陷图判 pass → FN；
  无缺陷图报警 → FP；无缺陷图 pass → TN。``confusion_matrix`` 为
  ``[[TN, FP], [FN, TP]]``（行为真值、列为预测）。
* **缺陷级**：逐图做贪心 IoU 匹配 —— 把所有 IoU ≥ ``iou_threshold`` 的
  (annotation, prediction) 候选对按 IoU 降序排列（IoU 相同按索引字典序，保证
  确定性），每轮取当前最大对匹配，双方出池；因此**同一预测不得重复匹配**，
  同一 annotation 也只匹配一次。匹配对计 defect TP；未匹配预测计 FP；
  未匹配 annotation 计 FN。
* **per_class**：``tp``/``fp`` 按**预测类别**统计（匹配对的预测标签计 tp，
  未匹配预测按其预测标签计 fp）；``fn`` 按未匹配 annotation 的真值类别统计。
  类别预测错误时计入预测类的 tp，真值类不计 fn（该真值已被匹配）。
* **latency_ms**：预测条目可附带 ``"processing_ms"`` 字段，存在时聚合
  mean/p50/p95/max；条目不带该字段时为全 0，调用方可在返回的 dict 上直接
  覆盖注入真实计时。

**所有除法均防零除**：分母为 0 时对应指标取 0.0，绝不抛异常。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..contracts import DECISION_PASS, DEFECT_CLASSES


# --------------------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Annotation:
    """单个缺陷的人工/合成真值。

    Attributes:
        defect_class: 缺陷类别，契约上必须 ∈ :data:`DEFECT_CLASSES`。
        bbox: ``(x, y, w, h)`` 整数框，左上角原点、像素坐标。
        score: 该缺陷的主观严重度 ∈ ``[0, 1]``。
        features: 几何/灰度特征，必含 ``"length"`` / ``"width"`` /
            ``"depth"`` / ``"contrast"`` 四个键。
    """

    defect_class: str
    bbox: tuple[int, int, int, int]
    score: float
    features: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "defect_class": self.defect_class,
            "bbox": [int(v) for v in self.bbox],
            "score": round(float(self.score), 4),
            "features": {k: round(float(v), 4) for k, v in self.features.items()},
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Annotation":
        return Annotation(
            defect_class=str(d["defect_class"]),
            bbox=tuple(int(v) for v in d["bbox"]),
            score=float(d["score"]),
            features={str(k): float(v) for k, v in d.get("features", {}).items()},
        )


@dataclass
class GroundTruth:
    """一张图的完整真值记录（manifest 的一个条目）。"""

    image_id: str
    scene_id: str
    image_path: str
    annotations: list[Annotation] = field(default_factory=list)

    @property
    def is_defective(self) -> bool:
        """有 ≥1 条 annotation 即视为缺陷图。"""
        return len(self.annotations) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "scene_id": self.scene_id,
            "image_path": self.image_path,
            "annotations": [a.to_dict() for a in self.annotations],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "GroundTruth":
        return GroundTruth(
            image_id=str(d["image_id"]),
            scene_id=str(d["scene_id"]),
            image_path=str(d["image_path"]),
            annotations=[Annotation.from_dict(a) for a in d.get("annotations", [])],
        )


# --------------------------------------------------------------------------------------
# manifest 读写
# --------------------------------------------------------------------------------------


def write_manifest(truths: list[GroundTruth], path: str) -> None:
    """把真值列表写成 JSON manifest（``ensure_ascii=False, indent=2``）。"""
    payload = {"n_images": len(truths), "items": [t.to_dict() for t in truths]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def read_manifest(path: str) -> list[GroundTruth]:
    """读取 manifest，返回 :class:`GroundTruth` 列表。"""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return [GroundTruth.from_dict(d) for d in payload.get("items", [])]


# --------------------------------------------------------------------------------------
# 几何与指标基础
# --------------------------------------------------------------------------------------


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """``(x, y, w, h)`` 格式两框的 IoU；任一框退化或零除 → 0.0。"""
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return _safe_div(inter, union)


def _safe_div(num: float, den: float) -> float:
    """防零除除法：分母 ≤ 0 或非有限 → 0.0。"""
    if den <= 0.0 or not math.isfinite(den):
        return 0.0
    val = num / den
    return float(val) if math.isfinite(val) else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """由 tp/fp/fn 计算 precision/recall/f1（全部防零除）。"""
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2.0 * precision * recall, precision + recall)
    return {
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _image_metrics(tp: int, fp: int, tn: int, fn: int) -> dict[str, Any]:
    """图像级混淆矩阵 → 指标块。"""
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2.0 * precision * recall, precision + recall)
    return {
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(_safe_div(tp + tn, tp + fp + tn + fn), 6),
        "specificity": round(_safe_div(tn, tn + fp), 6),
        "false_positive_rate": round(_safe_div(fp, fp + tn), 6),
        "false_negative_rate": round(_safe_div(fn, fn + tp), 6),
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
    }


def _percentile(sorted_vals: list[float], q: float) -> float:
    """最近邻法分位数（确定性、无插值依赖）。"""
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def _pred_bbox(p: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """从预测条目提取 (x, y, w, h)；缺失/非法 → None。"""
    try:
        raw = p["bbox"]
        b = tuple(float(v) for v in raw)
    except (KeyError, TypeError, ValueError):
        return None
    if len(b) != 4:
        return None
    return b  # type: ignore[return-value]


def _greedy_match(
    anns: list[Annotation],
    preds: list[dict[str, Any]],
    iou_threshold: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """单图贪心 IoU 匹配。

    Returns:
        ``(matched_pairs, unmatched_ann, unmatched_pred)``，
        匹配对为 (annotation 下标, prediction 下标)；同预测/同真值均不重复匹配。
    """
    cands: list[tuple[float, int, int]] = []
    for i, ann in enumerate(anns):
        for j, p in enumerate(preds):
            pb = _pred_bbox(p)
            if pb is None:
                continue
            iou = bbox_iou(ann.bbox, pb)  # type: ignore[arg-type]
            if iou >= iou_threshold:
                cands.append((iou, i, j))
    # IoU 降序，相同则按 (ann_idx, pred_idx) 字典序 → 确定性贪心
    cands.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_ann: set[int] = set()
    used_pred: set[int] = set()
    matched: list[tuple[int, int]] = []
    for iou, i, j in cands:
        if i in used_ann or j in used_pred:
            continue
        used_ann.add(i)
        used_pred.add(j)
        matched.append((i, j))
    unmatched_ann = [i for i in range(len(anns)) if i not in used_ann]
    unmatched_pred = [j for j in range(len(preds)) if j not in used_pred]
    return matched, unmatched_ann, unmatched_pred


# --------------------------------------------------------------------------------------
# 主评测入口
# --------------------------------------------------------------------------------------


def evaluate_detections(
    truths: list[GroundTruth],
    predictions: dict[str, list[dict[str, Any]]],
    image_decisions: dict[str, str],
    iou_threshold: float = 0.30,
) -> dict[str, Any]:
    """对照真值评估检测结果，返回可直接被 S3/Web 展示的完整报告。

    Args:
        truths: 全部真值记录（评估范围以此为准；``predictions`` 中多余的
            image_id 被忽略）。
        predictions: ``image_id -> [{"bbox": [x, y, w, h],
            "defect_class": str, "score": float}, ...]``，条目可附带
            ``processing_ms`` 供延迟聚合。
        image_decisions: ``image_id -> "pass"/"review"/"fail"``；缺省按
            ``"pass"`` 处理。
        iou_threshold: 缺陷级匹配的 IoU 下限。

    Returns:
        结构冻结的报告 dict（iou_threshold / n_images / n_defective_images /
        n_ok_images / image_metrics / defect_metrics / per_class / per_scene /
        latency_ms / score_separation / failures）。判定口径与零除防护见模块
        docstring。
    """
    img_tp = img_fp = img_tn = img_fn = 0
    d_tp = d_fp = d_fn = 0
    per_class: dict[str, dict[str, int]] = {
        cls: {"tp": 0, "fp": 0, "fn": 0} for cls in DEFECT_CLASSES
    }
    failures: list[dict[str, Any]] = []
    latencies: list[float] = []
    ok_scores: list[float] = []
    ng_scores: list[float] = []

    # 分场景累积器
    scene_acc: dict[str, dict[str, int]] = {}

    for truth in truths:
        anns = truth.annotations
        preds = list(predictions.get(truth.image_id, []))
        decision = image_decisions.get(truth.image_id, DECISION_PASS)
        defective = truth.is_defective

        acc = scene_acc.setdefault(
            truth.scene_id,
            {"img_tp": 0, "img_fp": 0, "img_tn": 0, "img_fn": 0, "d_tp": 0, "d_fp": 0, "d_fn": 0},
        )

        # 逐预测收集延迟（字段缺失/非法则跳过）
        for p in preds:
            raw_ms = p.get("processing_ms") if isinstance(p, dict) else None
            try:
                if raw_ms is not None:
                    ms = float(raw_ms)
                    if math.isfinite(ms):
                        latencies.append(ms)
            except (TypeError, ValueError):
                pass

        # ---- 缺陷级：贪心 IoU 匹配，同预测不重复匹配 ----
        matched, unm_ann, unm_pred = _greedy_match(anns, preds, iou_threshold)
        d_tp += len(matched)
        acc["d_tp"] += len(matched)
        for i, j in matched:
            slot = per_class.get(str(preds[j].get("defect_class", "")))
            if slot is not None:
                slot["tp"] += 1
        d_fn += len(unm_ann)
        acc["d_fn"] += len(unm_ann)
        for i in unm_ann:
            slot = per_class.get(anns[i].defect_class)
            if slot is not None:
                slot["fn"] += 1
        d_fp += len(unm_pred)
        acc["d_fp"] += len(unm_pred)
        for j in unm_pred:
            slot = per_class.get(str(preds[j].get("defect_class", "")))
            if slot is not None:
                slot["fp"] += 1

        # ---- 图像级 ----
        alarm = decision != DECISION_PASS
        if defective and alarm:
            img_tp += 1
            acc["img_tp"] += 1
        elif defective and not alarm:
            img_fn += 1
            acc["img_fn"] += 1
            failures.append(
                {
                    "image_id": truth.image_id,
                    "kind": "false_negative",
                    "detail": (
                        f"缺陷图（{len(anns)} 条真值）被判 pass，"
                        f"漏检 {len(unm_ann)} 条"
                    ),
                }
            )
        elif not defective and alarm:
            img_fp += 1
            acc["img_fp"] += 1
            failures.append(
                {
                    "image_id": truth.image_id,
                    "kind": "false_positive",
                    "detail": f"无缺陷图报警 decision={decision}",
                }
            )
        else:
            img_tn += 1
            acc["img_tn"] += 1

        for i in unm_ann:
            ann = anns[i]
            failures.append(
                {
                    "image_id": truth.image_id,
                    "kind": "missed_defect",
                    "detail": (
                        f"{ann.defect_class} bbox={list(ann.bbox)} "
                        f"score={ann.score:.2f} 未被 IoU≥{iou_threshold} 匹配"
                    ),
                }
            )

        # 图级 score：该图预测 score 的最大值（无预测 → 0.0）
        try:
            img_score = max((float(p.get("score", 0.0)) for p in preds), default=0.0)
        except (TypeError, ValueError):
            img_score = 0.0
        (ng_scores if defective else ok_scores).append(img_score)

    n_defective = sum(1 for t in truths if t.is_defective)
    n_ok = len(truths) - n_defective

    # ---- score 分离度 ----
    ok_max = max(ok_scores, default=0.0)
    ng_min = min(ng_scores) if ng_scores else 0.0
    score_separation = {
        "ok_max": round(ok_max, 6),
        "defective_min": round(ng_min, 6),
        "gap": round(ng_min - ok_max, 6),
    }

    # ---- 延迟（调用方可覆盖注入真实计时）----
    latencies.sort()
    latency_ms = {
        "mean": round(_safe_div(sum(latencies), len(latencies)), 3),
        "p50": round(_percentile(latencies, 0.50), 3),
        "p95": round(_percentile(latencies, 0.95), 3),
        "max": round(latencies[-1], 3) if latencies else 0.0,
    }

    per_scene = {
        scene: {
            "image_metrics": _image_metrics(a["img_tp"], a["img_fp"], a["img_tn"], a["img_fn"]),
            "defect_metrics": _prf(a["d_tp"], a["d_fp"], a["d_fn"]),
        }
        for scene, a in scene_acc.items()
    }

    return {
        "iou_threshold": float(iou_threshold),
        "n_images": len(truths),
        "n_defective_images": int(n_defective),
        "n_ok_images": int(n_ok),
        "image_metrics": _image_metrics(img_tp, img_fp, img_tn, img_fn),
        "defect_metrics": _prf(d_tp, d_fp, d_fn),
        "per_class": {cls: _prf(v["tp"], v["fp"], v["fn"]) for cls, v in per_class.items()},
        "per_scene": per_scene,
        "latency_ms": latency_ms,
        "score_separation": score_separation,
        "failures": failures,
    }


__all__ = [
    "Annotation",
    "GroundTruth",
    "write_manifest",
    "read_manifest",
    "bbox_iou",
    "evaluate_detections",
]