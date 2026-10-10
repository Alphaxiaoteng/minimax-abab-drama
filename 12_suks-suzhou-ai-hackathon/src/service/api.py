"""S3 在线质检服务（FastAPI 应用，模块路径 ``service.api:app``）。

职责
----
* 把 :mod:`inspectai.contracts` 冻结契约暴露为 HTTP 接口（health / config / scenes）；
* 上传图检测 ``/api/v1/inspect``（含场景自动推断）；
* 服务端合成图检测与基准评测（``/api/v1/inspect/demo``、``/api/v1/dataset/*``）。

说明：检测引擎（``inspectai.detectors.core``）与合成生成器
（``inspectai.domain.generator``）由 S1/S2 并行开发，本模块**一律惰性 import**，
即使它们尚未就绪，``from service.api import app`` 也必须成功。
"""

from __future__ import annotations

import base64
import logging
import math
import time
from pathlib import Path
from typing import Any, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from inspectai.contracts import (
    CLASS_CN,
    CONTRACT_VERSION,
    DEFAULT_CONFIG,
    DEFECT_CLASSES,
    SCENE_CN,
    SCENE_IDS,
    SCENE_PROFILES,
    SC_GEAR,
    DetectionResult,
)

logger = logging.getLogger("service.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

MODEL_ID = "inspectai-hybrid-v1"
"""``/api/v1/health`` 回显的引擎标识。"""

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
"""上传体积上限（20MB），超限返回 HTTP 413。"""

STATIC_DIR = Path(__file__).resolve().parent / "static"
"""前端静态目录，始终以本文件位置定位，禁止依赖进程 CWD。"""

# --------------------------------------------------------------------------------------
# 场景自动推断（最近邻匹配）
# --------------------------------------------------------------------------------------

_GRAD_SCALE = 0.5 / 255.0
"""Sobel 梯度均值 → ``gradient_prior`` 同量纲的经验标定系数。"""

_GRAD_EPS = 1e-6
"""对数距离的防零常数。"""


def _to_gray(image: np.ndarray) -> np.ndarray:
    """统一转单通道 ``uint8`` 灰度（兼容 1/3/4 通道输入）。"""
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image[..., :3], cv2.COLOR_BGR2GRAY)


def _gradient_energy(gray: np.ndarray) -> float:
    """Sobel 梯度幅值均值（归一化），对应 ``SceneProfile.gradient_prior``。"""
    sx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return float(cv2.magnitude(sx, sy).mean()) * _GRAD_SCALE


def _dominant_period(gray: np.ndarray) -> Optional[float]:
    """FFT 径向功率谱主峰 → 纹理主周期（像素）。

    取结构频段（周期约 2.9–50px）内功率最大的频率，要求该峰所在
    ±10%% 频带内的功率占总功率比例 ≥ 8%%，否则视为"无显著周期"返回 ``None``。
    """
    work = gray.astype(np.float64)
    work -= work.mean()
    spec = np.abs(np.fft.rfft2(work)) ** 2
    total = float(spec.sum())
    if total <= 0.0:
        return None
    h, w = work.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    r = np.sqrt(fx * fx + fy * fy)
    mask = (r >= 0.02) & (r <= 0.35)
    power = np.where(mask, spec, 0.0)
    if not power.any():
        return None
    iy, ix = np.unravel_index(int(power.argmax()), power.shape)
    peak = float(r[iy, ix])
    if peak <= 0.0:
        return None
    band = (r >= peak * 0.9) & (r <= peak * 1.1) & mask
    frac = float(spec[band].sum()) / total
    if frac < 0.08:
        return None
    return 1.0 / peak


def guess_scene(image: np.ndarray) -> str:
    """对上传图像自动推断质检场景（``/api/v1/inspect`` 的 ``scene_id=auto`` 路径）。

    距离度量（越小越接近）——对每个已登记场景 profile 计算：

    * 梯度项 ``|ln((g_meas+ε)/(gradient_prior+ε))|``：实测 Sobel 梯度能量与先验
      的对数比，捕捉"强纹理（齿轮）→ 弱纹理（冲压件）"的量级差异；
    * 周期项 ``|ln(period_meas/period_hint)|``：FFT 主周期与 profile 提示周期的
      对数比；profile 无 ``period_hint`` 时该项记 0（中性），profile 有提示而
      实测无显著周期时记固定惩罚 1.0，避免弱纹理场景无条件胜出。

    两项直接相加（等权），在全场景上取最小者；对全黑/退化图像返回梯度先验
    最接近的场景 id，保证始终返回合法字符串。
    """
    gray = _to_gray(image)
    g_meas = _gradient_energy(gray)
    period = _dominant_period(gray)
    best_scene = SCENE_IDS[0]
    best_dist = math.inf
    for sid, prof in SCENE_PROFILES.items():
        dist = abs(math.log((g_meas + _GRAD_EPS) / (prof.gradient_prior + _GRAD_EPS)))
        if prof.period_hint is not None:
            if period is not None:
                dist += abs(math.log(period / prof.period_hint))
            else:
                dist += 1.0
        if dist < best_dist:
            best_dist = dist
            best_scene = sid
    return best_scene


# --------------------------------------------------------------------------------------
# 惰性依赖（S1 检测引擎 / S2 合成生成器）
# --------------------------------------------------------------------------------------

_DETECTOR_CACHE: dict[str, Any] = {}


def _get_detector() -> Any:
    """惰性获取检测引擎单例；S1 未就绪时返回 503 而非拖垮服务启动。"""
    if "d" not in _DETECTOR_CACHE:
        try:
            from inspectai.detectors.core import get_detector  # noqa: PLC0415（惰性 import）
        except Exception as exc:  # 引擎由其他 agent 并行交付，容忍 import 期缺失
            raise HTTPException(status_code=503, detail=f"检测引擎不可用：{exc}") from exc
        _DETECTOR_CACHE["d"] = get_detector(None)
    return _DETECTOR_CACHE["d"]


def _get_generator(scene_id: str, seed: Optional[int]) -> Any:
    """惰性构造合成图生成器（S2 未就绪时返回 503）。"""
    try:
        from inspectai.domain.generator import (  # noqa: PLC0415（惰性 import）
            SyntheticPartGenerator,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"合成生成器不可用：{exc}") from exc
    return SyntheticPartGenerator(scene_id=scene_id, seed=seed)


def _run_inspection(
    image: np.ndarray, image_id: str, scene_id: str
) -> tuple[DetectionResult, float]:
    """跑一次检测并计时；结构化中文日志覆盖 image_id/decision/score/processing_ms。"""
    t0 = time.perf_counter()
    result = _get_detector().inspect(image, image_id=image_id, scene_id=scene_id)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "质检完成 | image_id=%s | scene_id=%s | decision=%s | score=%.4f | processing_ms=%.1f",
        result.image_id,
        scene_id,
        result.decision,
        result.score,
        elapsed_ms,
    )
    return result, elapsed_ms


# --------------------------------------------------------------------------------------
# 请求模型
# --------------------------------------------------------------------------------------


class DemoRequest(BaseModel):
    """``/api/v1/inspect/demo`` 的 JSON 请求体。"""

    scene_id: Optional[str] = None
    has_defect: bool = True
    n_defects: Optional[int] = None
    seed: Optional[int] = None


class BenchmarkRequest(BaseModel):
    """``/api/v1/dataset/benchmark`` 的 JSON 请求体。"""

    n_ok: int = Field(20, ge=0, le=200)
    n_ng: int = Field(30, ge=0, le=200)
    scenes: Optional[List[str]] = None
    iou_threshold: float = Field(0.30, gt=0.0, le=1.0)


# --------------------------------------------------------------------------------------
# 应用与通用响应工具
# --------------------------------------------------------------------------------------

app = FastAPI(
    title="InspectAI 工业质检服务",
    version=CONTRACT_VERSION,
    description="长三角工业质检 Hackathon · S3 在线服务层",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _png_b64(image: np.ndarray) -> str:
    """图像 → PNG base64（响应体内联预览用）。"""
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise HTTPException(status_code=500, detail="PNG 编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _decode_image(data: bytes) -> np.ndarray:
    """上传字节 → cv2 图像；解码失败统一 400。"""
    arr = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise HTTPException(status_code=400, detail="无法解码图像文件")
    return image


def _validate_scene(scene_id: Optional[str]) -> str:
    """校验场景 id；未登记场景 → 400。"""
    if scene_id not in SCENE_PROFILES:
        raise HTTPException(status_code=400, detail=f"未知场景：{scene_id!r}")
    return str(scene_id)


def _resolve_scene(scene_id: Optional[str], image: Optional[np.ndarray]) -> str:
    """空 / ``"auto"`` → 自动推断；显式 id → 校验。"""
    if scene_id is None or scene_id.strip().lower() in ("", "auto"):
        assert image is not None
        return guess_scene(image)
    return _validate_scene(scene_id)


def _latency_block(values: list[float]) -> dict[str, float]:
    """延迟样本 → mean/p50/p95/max（最近邻分位，确定性）。"""
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(values)
    n = len(s)
    return {
        "mean": round(sum(s) / n, 3),
        "p50": round(s[int(round(0.50 * (n - 1)))], 3),
        "p95": round(s[min(n - 1, int(round(0.95 * (n - 1))))], 3),
        "max": round(s[-1], 3),
    }


def _scene_payload() -> list[dict[str, Any]]:
    """场景列表（含中文标签与 profile 原样透传）。"""
    return [
        {
            "id": sid,
            "label_cn": SCENE_CN.get(sid, sid),
            "profile": SCENE_PROFILES[sid].to_dict(),
        }
        for sid in SCENE_IDS
    ]


# --------------------------------------------------------------------------------------
# 静态与元信息路由
# --------------------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    """前端控制台首页。"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    """健康检查 + 契约版本回显。"""
    return {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "model": MODEL_ID,
        "scenes": [{"id": sid, "label_cn": SCENE_CN[sid]} for sid in SCENE_IDS],
    }


@app.get("/api/v1/config")
def config() -> dict[str, Any]:
    """全量阈值/权重 + 标签空间 + 场景先验，供前端零硬编码渲染。"""
    payload: dict[str, Any] = DEFAULT_CONFIG.to_dict()
    payload["contract_version"] = CONTRACT_VERSION
    payload["defect_classes"] = [
        {"id": cls, "label_cn": CLASS_CN[cls]} for cls in DEFECT_CLASSES
    ]
    payload["scenes"] = _scene_payload()
    return payload


@app.get("/api/v1/scenes")
def scenes() -> dict[str, Any]:
    """场景列表（含 profile）。"""
    return {"scenes": _scene_payload()}


# --------------------------------------------------------------------------------------
# 检测路由
# --------------------------------------------------------------------------------------


@app.post("/api/v1/inspect")
async def inspect_upload(
    file: UploadFile = File(...),
    scene_id: Optional[str] = Form(None),
    include_overlay: bool = Form(True),
) -> dict[str, Any]:
    """multipart 上传检测。

    * ``file`` 必填；>20MB → 413；非图像 MIME / 解码失败 → 400。
    * ``scene_id`` 空或 ``"auto"`` 时用 :func:`guess_scene` 自动推断并回显。
    * ``include_overlay=False`` 时剥离 ``overlay_png_b64`` 以缩减响应体。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件大小超过 20MB 上限")
    ctype = (file.content_type or "").lower()
    # octet-stream 是命令行/脚本上传的常见缺省，放行；其余非 image/* 一律 400
    if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ctype}")

    image = _decode_image(data)
    scene = _resolve_scene(scene_id, image)
    stem = Path(file.filename or "").stem
    image_id = stem if stem else "upload"
    result, elapsed_ms = _run_inspection(image, image_id, scene)
    if not include_overlay:
        result.overlay_png_b64 = None
    return {
        "result": result.to_dict(),
        "scene_id": scene,
        "elapsed_ms": round(elapsed_ms, 2),
    }


@app.post("/api/v1/inspect/demo")
def inspect_demo(req: DemoRequest) -> dict[str, Any]:
    """服务端合成一张图 → 检测，返回与上传检测同构的结果 + 真值 + 内联 PNG。"""
    # demo 的图像在检测前还不存在，无法跑 guess_scene；空/auto/缺省一律落到默认场景
    scene = SC_GEAR if not req.scene_id or req.scene_id.strip().lower() == "auto" else _validate_scene(req.scene_id)
    gen = _get_generator(scene, req.seed)
    has_defect = bool(req.has_defect)
    image, truth = gen.generate(
        has_defect=has_defect,
        n_defects=req.n_defects if has_defect else None,
    )
    result, elapsed_ms = _run_inspection(image, truth.image_id or "demo", scene)
    return {
        "result": result.to_dict(),
        "scene_id": scene,
        "elapsed_ms": round(elapsed_ms, 2),
        "ground_truth": truth.to_dict(),
        "image_png_b64": _png_b64(image),
    }


# --------------------------------------------------------------------------------------
# 数据与评测路由
# --------------------------------------------------------------------------------------


@app.post("/api/v1/dataset/benchmark")
def dataset_benchmark(req: BenchmarkRequest) -> dict[str, Any]:
    """批量合成 → 逐图检测 → ``evaluate_detections`` 出完整评估报告。

    ``n_ok`` / ``n_ng`` 为跨场景总量（逐场景向上取整分配）；
    ``n_ok`` / ``n_ng`` 为跨场景总量（逐场景向上取整分配）。
    评测完成后由本路由**覆盖注入**报告里的 ``latency_ms`` 与 ``score_separation``。
    评测完成后必须由本路由**覆盖注入** ``latency_ms`` 与 ``score_separation``：
    评测器仅统计携带预测条目的图（无缺陷图会被漏掉），故用全量逐图计时与各图
    ``DetectionResult.score`` 重新计算。
    """
    from inspectai.domain.groundtruth import (  # noqa: PLC0415（惰性 import）
        evaluate_detections,
    )

    scene_list = req.scenes if req.scenes else list(SCENE_IDS)
    for sid in scene_list:
        _validate_scene(sid)
    if not scene_list:
        raise HTTPException(status_code=400, detail="scenes 不能为空")

    n_scenes = len(scene_list)
    per_ok = int(math.ceil(req.n_ok / n_scenes))
    per_ng = int(math.ceil(req.n_ng / n_scenes))

    truths: list[Any] = []
    predictions: dict[str, list[dict[str, Any]]] = {}
    decisions: dict[str, str] = {}
    scores: dict[str, float] = {}
    lat_all: list[float] = []
    lat_by_scene: dict[str, list[float]] = {}

    for scene in scene_list:
        base_seed = SCENE_PROFILES[scene].seed
        idx = 0
        for kind, count, defective in (("ok", per_ok, False), ("ng", per_ng, True)):
            for i in range(count):
                gen = _get_generator(scene, base_seed + idx)
                image, truth = gen.generate(has_defect=defective, n_defects=None)
                idx += 1
                image_id = f"{scene}-{kind}-{i:03d}"
                truth.image_id = image_id
                truth.scene_id = scene
                truth.image_path = f"data/benchmark/{image_id}.png"
                result, ms = _run_inspection(image, image_id, scene)
                # 契约规定缺陷 bbox 落在底分辨率热力图坐标系（heatmap_shape），
                # 而真值 bbox 是原图像素坐标；直接比对会让 IoU 恒≈0（跨尺度）。
                # 这里按 原图/热力图 的边长比把预测框升采样回原图坐标再交给评测器。
                bh, bw = result.heatmap_shape
                sx = result.width / float(max(1, bw))
                sy = result.height / float(max(1, bh))
                preds: list[dict[str, Any]] = []
                for d in result.defects:
                    x1, y1, x2, y2 = d.bbox
                    ox1 = int(round(x1 * sx))
                    oy1 = int(round(y1 * sy))
                    ox2 = min(result.width - 1, int(round((x2 + 1) * sx)) - 1)
                    oy2 = min(result.height - 1, int(round((y2 + 1) * sy)) - 1)
                    preds.append(
                        {
                            "bbox": [ox1, oy1, max(1, ox2 - ox1 + 1), max(1, oy2 - oy1 + 1)],
                            "defect_class": d.defect_class,
                            "score": round(float(d.score), 4),
                            "processing_ms": round(ms, 3),
                        }
                    )
                truths.append(truth)
                predictions[image_id] = preds
                decisions[image_id] = result.decision
                scores[image_id] = float(result.score)
                lat_all.append(ms)
                lat_by_scene.setdefault(scene, []).append(ms)

    report = evaluate_detections(
        truths,
        predictions,
        decisions,
        iou_threshold=req.iou_threshold,
    )
    # 覆盖注入：score_separation 以图级融合得分（非缺陷级 score 最大值）为口径
    ok_vals = [scores[t.image_id] for t in truths if not t.is_defective]
    ng_vals = [scores[t.image_id] for t in truths if t.is_defective]
    ok_max = max(ok_vals, default=0.0)
    ng_min = min(ng_vals, default=0.0)
    report["latency_ms"] = _latency_block(lat_all)
    report["score_separation"] = {
        "ok_max": round(ok_max, 6),
        "defective_min": round(ng_min, 6),
        "gap": round(ng_min - ok_max, 6),
    }
    logger.info(
        "基准评测完成 | n_images=%d | defect_f1=%.4f | gap=%.4f",
        len(truths),
        report["defect_metrics"]["f1"],
        report["score_separation"]["gap"],
    )
    return {
        "report": report,
        "latency_ms": _latency_block(lat_all),
        "generated": {"n_images": len(truths)},
        "per_scene_latency": {
            scene: _latency_block(vals) for scene, vals in lat_by_scene.items()
        },
    }


@app.get("/api/v1/dataset/sample")
def dataset_sample(
    scene_id: str = Query(SC_GEAR),
    has_defect: bool = Query(True),
    seed: Optional[int] = Query(None),
) -> dict[str, Any]:
    """返回一张合成样例图（PNG base64）+ 真值，不跑检测。"""
    scene = _validate_scene(scene_id)
    image, truth = _get_generator(scene, seed).generate(
        has_defect=has_defect, n_defects=None
    )
    return {
        "image_png_b64": _png_b64(image),
        "ground_truth": truth.to_dict(),
        "scene_id": scene,
    }


@app.get("/api/v1/samples")
def samples() -> dict[str, Any]:
    """``static/samples/`` 样例图清单；目录不存在时返回空列表（不报错）。"""
    samples_dir = STATIC_DIR / "samples"
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    names: list[str] = []
    if samples_dir.is_dir():
        names = sorted(
            p.name for p in samples_dir.iterdir() if p.suffix.lower() in exts
        )
    return {"samples": [{"name": n, "url": f"/static/samples/{n}"} for n in names]}


# 静态资源挂载（放在路由注册之后；/static 前缀不与任何 API 路径冲突）
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


__all__ = ["app", "guess_scene"]
