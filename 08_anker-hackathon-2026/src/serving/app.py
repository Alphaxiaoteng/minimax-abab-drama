"""serving.app — FastAPI 应用与仪表盘服务。

三层架构的服务入口:HTTP API + SSE 实时流 + 单页仪表盘。
依赖方向:serving → agent → core、serving → edge → core。
启动时才构建 demo 状态(惰性),`import serving.app` 本身不做重活。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import replace, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from serving.api import HealthResponse, PlanRequest, ScenarioComparisonRequest, ROIReportRequest

VERSION = "1.0.0"

# web 静态目录:serving/ 与 web/ 在 src/ 下同级
_WEB_ROOT = (Path(__file__).resolve().parent.parent / "web")

# 平均基础负荷 kW(demo_site().load_kw 为 None 时使用);负荷序列 = base × 24 点归一化画像
_DEFAULT_BASE_LOAD_KW = 1.2
_DEMO_PV_KWP = 5.0

app = FastAPI(title="Anker 智能用电管家", version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 惰性核心装配:所有 core/edge/agent import 都在函数内,避免 import 期依赖
# 尚未落地的兄弟模块。
# --------------------------------------------------------------------------
def _tariff_for(city: str):
    from core.tariff import builtin_tariffs
    plans = builtin_tariffs()
    if city not in plans:
        raise HTTPException(
            status_code=422,
            detail={"error": "unknown city", "valid": sorted(plans.keys())},
        )
    return plans[city]


def _build_battery(model: str, capacity_kwh: Optional[float]):
    from core.battery import BatteryModel
    from core.hardware import HardwareCatalog
    cfg = HardwareCatalog().battery_config(model)
    if capacity_kwh is not None:
        cfg = replace(cfg, capacity_kwh=float(capacity_kwh))
    return BatteryModel(cfg)


def _preset_params(mode: str):
    """core.policy.mode_presets() 若存在则取之,否则回退默认 PolicyParams(mode)。

    契约 §3.6 未冻结 mode_presets,故防御式装配。
    """
    import core.policy as cp
    if hasattr(cp, "mode_presets"):
        presets = cp.mode_presets()
        if mode in presets:
            return replace(presets[mode])
    return cp.PolicyParams(mode=mode)


def _clamp(params):
    import core.policy as cp
    return cp.clamp_params(params, cp.GuardRails())


def _load_series(req: PlanRequest) -> List[float]:
    from core.hardware import demo_site
    if req.load_kw is not None:
        lv = list(req.load_kw)
        return _resample24(lv)
    site = demo_site()
    base = site.load_kw if site.load_kw else _DEFAULT_BASE_LOAD_KW
    profile = site.load_profile if len(site.load_profile) == 24 else [1.0] * 24
    return [round(base * c, 4) for c in profile]


def _pv_series(req: PlanRequest, weather) -> List[float]:
    from core.solar import SolarModel
    from core.hardware import demo_site
    if req.pv_kw is not None:
        return _resample24(list(req.pv_kw))
    solar = SolarModel(demo_site().pv_kwp or _DEMO_PV_KWP)
    fc = solar.forecast(weather)
    return [round(p, 4) for p in fc.pv_kw]


def _resample24(vals: List[float]) -> List[float]:
    """把任意长度时序(重)采样到 24 点(线性),空则补零。"""
    n = len(vals)
    if n == 0:
        return [0.0] * 24
    if n == 24:
        return [float(v) for v in vals]
    out: List[float] = []
    for i in range(24):
        pos = i * (n - 1) / 23.0
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        out.append(round(float(vals[lo]) * (1 - frac) + float(vals[hi]) * frac, 4))
    return out


def _current_hour() -> int:
    return int(time.localtime().tm_hour)


def _build_plan(req: PlanRequest) -> Dict[str, Any]:
    """装配一次 24h 调度并展平为响应载荷(契约 §3.11 额外字段)。"""
    from core.solar import synthetic_weather
    from core.optimizer import MPCOptimizer
    from core.explain import explain_plan

    tariff = _tariff_for(req.city)
    battery = _build_battery(req.model, req.capacity_kwh)
    weather = synthetic_weather(req.weather, seed=7)
    load = _load_series(req)
    pv = _pv_series(req, weather)

    params = _preset_params(req.mode)
    params.risk_aversion = req.risk_aversion
    params.reserve_soc = req.reserve_soc
    params = _clamp(params)

    llm_available = False
    llm_used = False
    llm_note: Optional[str] = None
    planner_explain: List[str] = []

    if req.use_llm:
        try:
            from agent.llm import LLMClient
            from agent.planner import PlannerAgent
            client = LLMClient()
            llm_available = bool(client.available)
            if llm_available:
                planner = PlannerAgent(client, tariff)
                dp = planner.plan(weather, load, battery.cfg.soc_start)
                if dp.source == "llm":
                    params = dp.params
                    params.risk_aversion = req.risk_aversion
                    params.reserve_soc = req.reserve_soc
                    params = _clamp(params)
                    llm_used = True
                    try:
                        planner_explain = list(planner.explain(MPCOptimizer(battery, tariff, params).optimize(load, pv)))
                    except Exception:
                        planner_explain = list(dp.rationale)
                    llm_note = "LLM 策略已应用(%s)" % (client.cfg.model,)
                else:
                    err = getattr(client, "last_error", "") or ""
                    llm_note = "LLM 不可用或解析失败,回退规则策略" + ("(%s)" % err if err else "")
            else:
                llm_note = "未检测到 %s,LLM 不可用,回退规则策略" % (client.cfg.api_key_env,)
        except HTTPException:
            raise
        except Exception as exc:  # planner/llm 模块缺失等 → 确定性回退
            llm_note = "LLM 分支异常,回退规则策略(%s)" % (exc.__class__.__name__,)

    # 非 LLM 路径仍需报告 llm_available(供仪表盘 AI 面板显示)
    if not req.use_llm:
        try:
            from agent.llm import LLMClient
            llm_available = bool(LLMClient().available)
        except Exception:
            llm_available = False

    optimizer = MPCOptimizer(battery, tariff, params)
    res = optimizer.optimize(load, pv)

    payload = dict(res.to_dict())
    base_explain = list(explain_plan(res))
    if llm_used and planner_explain:
        merged = list(base_explain)
        for line in planner_explain:
            if line not in merged:
                merged.append(line)
        base_explain = merged

    # 当前小时状态
    hour = _current_hour()
    points = payload.get("points", [])
    soc_now = battery.cfg.soc_start
    for p in points:
        if int(round(float(p.get("hour", -1)))) == hour:
            soc_now = float(p.get("soc", soc_now))
            break

    payload["model"] = req.model
    payload["city"] = req.city
    payload["params"] = asdict(params)
    payload["explain"] = base_explain
    payload["soc_now"] = round(float(soc_now), 4)
    payload["tier_now"] = tariff.tier_at(hour)
    payload["price_now"] = round(float(tariff.price_at(hour)), 4)
    payload["llm_available"] = llm_available
    payload["llm_used"] = llm_used
    payload["llm_note"] = llm_note
    if "source" not in payload:
        payload["source"] = "llm" if llm_used else "rule_fallback"
    payload.setdefault("llm_model", _llm_model_name())
    payload["_battery"] = battery  # 供 stream 复用(不序列化)
    payload["_tariff"] = tariff
    payload["_weather"] = weather
    return payload


def _llm_model_name() -> str:
    try:
        from agent.llm import LLMConfig
        return LLMConfig().model
    except Exception:
        return "n/a"


# --------------------------------------------------------------------------
# 静态资源与仪表盘
# --------------------------------------------------------------------------
@app.get("/")
def read_root() -> FileResponse:
    index = _WEB_ROOT / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=500, detail="index.html 未找到")
    return FileResponse(str(index), media_type="text/html")


@app.get("/web/{path:path}")
def read_web_asset(path: str):
    if ".." in path.replace("\\", "/").split("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    target = (_WEB_ROOT / path).resolve()
    root = _WEB_ROOT.resolve()
    if not str(target).startswith(str(root) + os.sep) or not target.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    media = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".png": "image/png",
    }.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(str(target), media_type=media)


# --------------------------------------------------------------------------
# 只读元数据接口
# --------------------------------------------------------------------------
@app.get("/api/health")
def api_health() -> HealthResponse:
    from core.hardware import HardwareCatalog
    from core.tariff import builtin_tariffs
    llm_available = False
    try:
        from agent.llm import LLMClient
        llm_available = bool(LLMClient().available)
    except Exception:
        llm_available = False
    return HealthResponse(
        status="ok",
        llm_available=llm_available,
        models=HardwareCatalog().models(),
        cities=sorted(builtin_tariffs().keys()),
        version=VERSION,
    )


@app.get("/api/hardware")
def api_hardware() -> Dict[str, Any]:
    from core.hardware import HardwareCatalog
    cat = HardwareCatalog()
    specs = [asdict(cat.get(m)) for m in cat.models()]
    matrix = {}
    try:
        if hasattr(cat, "adapter_matrix"):
            matrix = cat.adapter_matrix()
    except Exception:
        matrix = {}
    return {"models": specs, "adapter_matrix": matrix}


@app.get("/api/tariffs")
def api_tariffs() -> Dict[str, Any]:
    from core.tariff import builtin_tariffs
    out: Dict[str, Any] = {}
    for city, plan in builtin_tariffs().items():
        out[city] = {
            "currency": plan.currency,
            "export_price": plan.export_price,
            "spread": round(float(plan.spread()), 4),
            "tiers": [
                {
                    "name": t.name,
                    "start": t.start_hour,
                    "end": t.end_hour,
                    "price": t.price,
                }
                for t in plan.tiers
            ],
            "curve": [
                {"hour": h, "price": p, "tier": tr}
                for (h, p, tr) in plan.daily_curve(0.25)
            ],
        }
    return out


# --------------------------------------------------------------------------
# 计划接口
# --------------------------------------------------------------------------
def _request_from_query(
    city: str, model: str, mode: str, weather: str,
    risk_aversion: float, reserve_soc: float, use_llm: bool,
    load_kw: Optional[str], pv_kw: Optional[str], capacity_kwh: Optional[float],
) -> PlanRequest:
    def _parse_list(s: Optional[str]) -> Optional[List[float]]:
        if not s:
            return None
        return [float(x) for x in s.split(",") if x.strip() != ""]
    return PlanRequest(
        city=city, model=model, mode=mode, weather=weather,
        risk_aversion=risk_aversion, reserve_soc=reserve_soc, use_llm=use_llm,
        load_kw=_parse_list(load_kw), pv_kw=_parse_list(pv_kw),
        capacity_kwh=capacity_kwh,
    )


def _clean_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if not k.startswith("_")}


@app.get("/api/plan")
def api_plan_get(
    city: str = Query("shenzhen"),
    model: str = Query("SOLIX_F3800"),
    mode: str = Query("arbitrage"),
    weather: str = Query("clear"),
    risk_aversion: float = Query(0.5, ge=0.0, le=1.0),
    reserve_soc: float = Query(0.10, ge=0.0, le=1.0),
    use_llm: bool = Query(False),
    load_kw: Optional[str] = Query(None),
    pv_kw: Optional[str] = Query(None),
    capacity_kwh: Optional[float] = Query(None, gt=0.0),
) -> JSONResponse:
    try:
        req = _request_from_query(city, model, mode, weather, risk_aversion,
                                  reserve_soc, use_llm, load_kw, pv_kw, capacity_kwh)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=_pydantic_detail(exc))
    payload = _build_plan(req)
    _store_best_plan(payload)
    return JSONResponse(_clean_plan(payload))


@app.post("/api/plan")
def api_plan_post(req: PlanRequest) -> JSONResponse:
    payload = _build_plan(req)
    _store_best_plan(payload)
    return JSONResponse(_clean_plan(payload))


def _pydantic_detail(exc: Exception) -> Any:
    try:
        from pydantic import ValidationError
    except Exception:
        return str(exc)
    if isinstance(exc, ValidationError):
        return json.loads(exc.json())
    return str(exc)


# --------------------------------------------------------------------------
# demo 状态:SSE 与 simulate 复用最近一次最佳计划
# --------------------------------------------------------------------------
_DEMO: Dict[str, Any] = {"plan": None, "built_at": 0.0}


def _store_best_plan(payload: Dict[str, Any]) -> None:
    _DEMO["plan"] = {
        "city": payload["city"],
        "model": payload["model"],
        "points": payload.get("points", []),
        "battery": payload.get("_battery"),
        "tariff": payload.get("_tariff"),
        "weather": payload.get("_weather"),
    }
    _DEMO["built_at"] = time.time()


def _ensure_best_plan():
    """惰性构建默认计划,避免在无人调用 /api/plan 时 stream/simulate 无数据。"""
    if _DEMO["plan"] is not None:
        return _DEMO["plan"]
    payload = _build_plan(PlanRequest())
    _store_best_plan(payload)
    return _DEMO["plan"]


def _plant_from_best():
    """从最佳计划装配一个 PlantSimulator + TelemetryBus。"""
    from edge.plant import PlantSimulator
    from edge.telemetry import TelemetryBus
    from core.solar import SolarModel
    from core.hardware import demo_site
    best = _ensure_best_plan()
    battery = best["battery"]
    tariff = best["tariff"]
    weather = best["weather"]
    site = demo_site()
    from core.hardware import HomeLoad
    load = HomeLoad(base_kw=site.load_kw or _DEFAULT_BASE_LOAD_KW,
                    hourly_profile=list(site.load_profile))
    solar = SolarModel(site.pv_kwp or _DEMO_PV_KWP)
    plant = PlantSimulator(battery, load, solar, weather, tariff, seed=3)
    return plant, TelemetryBus(keep=5000), best


def _setpoint_for_hour(points: List[Dict[str, Any]], hour: float, default: float = 0.0) -> float:
    idx = int(hour) % 24
    for p in points:
        if int(round(float(p.get("hour", -1)))) == idx:
            return float(p.get("battery_kw", default))
    return default


# --------------------------------------------------------------------------
# SSE 实时流:后台 asyncio 任务推进数字孪生
# --------------------------------------------------------------------------
async def _stream_task(queue: "asyncio.Queue", points: List[Dict[str, Any]],
                       plant, bus, dt_hours: float, ticks: int) -> None:
    """每秒推一条 SiteReading;热浪天象由 weather 温度自然体现温升。"""
    hour = _current_hour() + (time.localtime().tm_min / 60.0)
    for _ in range(ticks):
        try:
            set_kw = _setpoint_for_hour(points, hour)
            reading = plant.step(hour, set_kw, dt_hours=dt_hours)
            bus.push(reading)
            row = reading.to_row()
            await queue.put(row)
        except Exception as exc:
            await queue.put({"error": str(exc)})
            break
        hour = (hour + dt_hours) % 24.0
        await asyncio.sleep(1.0)
    await queue.put(None)  # 结束哨兵


@app.get("/api/stream")
async def api_stream(request: Request) -> StreamingResponse:
    try:
        plant, bus, best = _plant_from_best()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="stream 依赖未就绪(%s)" % exc.__class__.__name__)

    points = best["points"]
    dt_hours = 0.2  # 120 秒走完一个 24h 日周期
    ticks = 120
    queue: "asyncio.Queue" = asyncio.Queue(maxsize=256)
    task = asyncio.ensure_future(_stream_task(queue, points, plant, bus, dt_hours, ticks))

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.5)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield "data: %s\n\n" % json.dumps(item, ensure_ascii=False)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------------------------------------------------------------------------
# 闭环仿真
# --------------------------------------------------------------------------
@app.get("/api/simulate")
def api_simulate(
    hours: int = Query(24, ge=1, le=168),
    interval: float = Query(0.25, gt=0.0, le=4.0),
) -> Dict[str, Any]:
    try:
        plant, bus, best = _plant_from_best()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="simulate 依赖未就绪(%s)" % exc.__class__.__name__)
    from core.optimizer import MPCOptimizer

    tariff = best["tariff"]
    battery = plant.battery if hasattr(plant, "battery") else best["battery"]
    params = _preset_params("arbitrage")
    params = _clamp(params)

    def optimizer_factory(p):
        return MPCOptimizer(battery, tariff, p)

    steps = max(1, int(round(hours / interval)))
    readings, replan_events = plant.run_closed_loop(tariff, optimizer_factory, params,
                                                    steps=steps, dt_hours=interval)

    rows = [r.to_row() for r in readings]
    # 实时电费:grid_kw>0 买电付费,grid_kw<0 卖电收益(按 export_price)
    realized = 0.0
    export_price = tariff.export_price
    for r in rows:
        g = float(r.get("grid_kw", 0.0))
        price = float(r.get("price", 0.0))
        dt = float(interval)
        if g >= 0:
            realized += g * price * dt
        else:
            realized += g * export_price * dt

    # 基准:无电池的同一时序反事实,电网 = 负荷 − 光伏(买电付费/卖电收益)。
    baseline = 0.0
    for r in rows:
        net = float(r.get("load_kw", 0.0)) - float(r.get("pv_kw", 0.0))
        price = float(r.get("price", 0.0))
        dt = float(interval)
        if net >= 0:
            baseline += net * price * dt
        else:
            baseline += net * export_price * dt
    savings_pct = ((baseline - realized) / baseline * 100.0) if baseline > 1e-9 else 0.0
    return {
        "readings": rows,
        "replan_events": replan_events,
        "baseline_cost": round(baseline, 4),
        "realized_cost": round(realized, 4),
        "savings_pct": round(savings_pct, 4),
    }


# --------------------------------------------------------------------------
# 新 Phase 2 功能：NILM 分解、场景矩阵、SOH/ROI
# --------------------------------------------------------------------------
@app.get("/api/appliances")
def api_appliances() -> Dict[str, Any]:
    """获取电器配置与状态。"""
    from core.appliance import NILMEngine, ApplianceType
    
    appliances = {
        ApplianceType.HEAT_PUMP: type('obj', (object,), {
            'type': ApplianceType.HEAT_PUMP,
            'max_power_kw': 3.0,
            'can_defer': True,
        })(),
        ApplianceType.EV_CHARGER: type('obj', (object,), {
            'type': ApplianceType.EV_CHARGER,
            'max_power_kw': 11.0,
            'can_defer': True,
        })(),
        ApplianceType.BASE_LOAD: type('obj', (object,), {
            'type': ApplianceType.BASE_LOAD,
            'max_power_kw': 1.0,
            'can_defer': False,
        })(),
        ApplianceType.LIGHTING: type('obj', (object,), {
            'type': ApplianceType.LIGHTING,
            'max_power_kw': 0.5,
            'can_defer': True,
        })(),
    }
    
    nilm = NILMEngine(appliances)
    breakdown = nilm.get_breakdown(_current_hour())
    
    return {
        "appliances": breakdown,
        "nilm_available": True,
        "scheduling_features": ["ev_smart_charging", "heat_pump_optimization", "load_shifting"],
    }


@app.post("/api/appliances/breakdown")
def api_appliance_breakdown(req: PlanRequest) -> JSONResponse:
    """家电负荷分解分析。"""
    from core.appliance import NILMEngine, ApplianceType
    
    appliances = {
        ApplianceType.HEAT_PUMP: type('obj', (object,), {
            'type': ApplianceType.HEAT_PUMP, 'max_power_kw': 3.0, 'min_power_kw': 0.3, 'can_defer': True,
        })(),
        ApplianceType.EV_CHARGER: type('obj', (object,), {
            'type': ApplianceType.EV_CHARGER, 'max_power_kw': 11.0, 'min_power_kw': 0.0, 'can_defer': True,
        })(),
        ApplianceType.BASE_LOAD: type('obj', (object,), {
            'type': ApplianceType.BASE_LOAD, 'max_power_kw': 1.0, 'min_power_kw': 0.5, 'can_defer': False,
        })(),
        ApplianceType.LIGHTING: type('obj', (object,), {
            'type': ApplianceType.LIGHTING, 'max_power_kw': 0.5, 'min_power_kw': 0.1, 'can_defer': True,
        })(),
    }
    
    load_series = _load_series(req)
    nilm = NILMEngine(appliances)
    
    breakdown_results = []
    for hour in range(24):
        total_load = load_series[hour]
        states = nilm.step(total_load, hour, dt_hours=1.0)
        breakdown = nilm.get_breakdown(hour)
        breakdown_results.append({"hour": hour, "total_load_kw": total_load, "breakdown": breakdown})
    
    return JSONResponse({
        "status": "ok",
        "daily_breakdown": breakdown_results,
        "summary": {
            "total_appliances": len(appliances),
            "schedulable_count": sum(1 for a in appliances.values() if a.can_defer),
            "peak_load_kw": max(load_series),
            "avg_load_kw": round(sum(load_series)/24, 2),
        }
    })


@app.get("/api/scenarios")
def api_scenarios() -> Dict[str, Any]:
    """获取预设工况列表。"""
    from core.scenarios import ScenarioMatrix
    
    return {
        "scenarios": ScenarioMatrix.list_scenarios(),
        "count": len(ScenarioMatrix.list_scenarios()),
    }


@app.post("/api/scenarios/compare")
def api_scenario_compare(req: ScenarioComparisonRequest) -> JSONResponse:
    """对比 MPC 优化与普通策略在特定场景下的收益。"""
    from core.scenarios import ScenarioMatrix, ScenarioType
    
    try:
        scenario_type = ScenarioType(req.scenario_type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown scenario: {req.scenario_type}")
    
    matrix = ScenarioMatrix()
    comparison = matrix.compare_strategies(scenario_type, req.mpc_savings_pct)
    
    return JSONResponse(comparison)


@app.get("/api/soh/status")
def api_soh_status(
    cycles_used: int = Query(1000, ge=0),
    days_calendar: int = Query(365, ge=0),
) -> SOHStatus:
    """获取电池健康度 SOH 状态。"""
    from core.soh_roi import BatteryDegradationModel
    
    model = BatteryDegradationModel()
    current_soh = model.get_soh(cycles_used, days_calendar)
    
    cycles_per_day = cycles_used / max(days_calendar, 1)
    remaining = model.predict_remaining_life(current_soh, cycles_per_day)
    
    degradation_rate = (1.0 - current_soh) / max(days_calendar / 365.0, 1) * 100  # % per year
    
    return SOHStatus(
        current_soh=current_soh,
        cycles_used=cycles_used,
        days_calendar=days_calendar,
        degradation_rate_per_year=degradation_rate,
        predicted_remaining_life=remaining,
    )


@app.post("/api/roi/report")
def api_roi_report(req: ROIReportRequest) -> ROIReport:
    """生成投资回报分析报告。"""
    from core.soh_roi import ROIPredictor
    
    predictor = ROIPredictor(
        battery_cost_cny=req.battery_cost_cny,
        annual_savings_cny=req.annual_savings_cny,
        annual_maintenance_cny=req.annual_maintenance_cny,
        carbon_credit_value=req.carbon_credit_value,
        annual_carbon_reduction_kg=req.carbon_reduction_kg,
    )
    
    payback = predictor.calculate_payback_period()
    lcoe = predictor.calculate_lcoe()
    npv_irr = predictor.calculate_npv_irr()
    
    return ROIReport(
        investment_summary={
            "total_initial_investment_cny": payback["total_initial_investment_cny"],
            "battery_share_pct": round(req.battery_cost_cny / payback["total_initial_investment_cny"] * 100, 1),
        },
        payback_analysis={
            "simple_years": payback["payback_period_simple_years"],
            "discounted_years": payback["payback_period_discounted_years"],
            "annual_net_benefit_cny": payback["annual_net_benefit_cny"],
        },
        lcoe_analysis={
            "lcoe_per_kwh": lcoe,
            "comparison_to_grid": "competitive" if lcoe < 0.65 else "expensive",
        },
        npv_irr_analysis=npv_irr,
        environmental_impact={
            "annual_carbon_kg": req.annual_carbon_reduction_kg,
            "lifecycle_carbon_kg": req.annual_carbon_reduction_kg * 20,
            "annual_trees_equiv": req.annual_carbon_reduction_kg / 15,  # 每棵树年吸收~15kg CO₂
            "annual_carbon_revenue": req.annual_carbon_reduction_kg * req.carbon_credit_value,
        },
        lifecycle_projection=[],  # 可扩展为年度现金流预测
    )


@app.get("/api/roi/export/html")
def api_roi_export_html(req: ROIReportRequest) -> str:
    """导出 HTML 格式 ROI 报告。"""
    report = api_roi_report(req)
    soh = api_soh_status()
    
    from core.soh_roi import generate_html_report
    path = f"/tmp/anker_roi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    generate_html_report(soh, report, path)
    
    return path


@app.get("/api/roi/export/pdf")
def api_roi_export_pdf(req: ROIReportRequest) -> str:
    """导出 PDF 格式 ROI 报告（需 reportlab）。"""
    report = api_roi_report(req)
    soh = api_soh_status()
    
    from core.soh_roi import generate_pdf_report
    path = f"/tmp/anker_roi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    generate_pdf_report(soh, report, path)
    
    return path
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("serving.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()