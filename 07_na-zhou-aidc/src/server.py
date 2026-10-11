"""轻量级仿真服务端 —— FastAPI + 静态看板。

接口
----
``GET /api/simulate``：按查询参数实时构建情景并调用 ``src.optimizer.solve``
求解 LP，返回 96 步调度序列与 KPI（JSON）。

参数（均有白名单/区间校验，非法输入直接 422）：
    scenario           : baseline_day | transient_spike | extreme_peak
    spike_multiplier   : 算力尖峰倍率，作用于 it_peak_kw，0.5 ~ 4.0
    battery            : 储能配置预设 key（见 BATTERY_PRESETS）
    tariff             : 分时电价方案 key（见 TARIFF_PRESETS）
    c_rate             : 电池充放电倍率限制 (C)，功率 = 容量 × C，0.2 ~ 1.0
    price_spread       : 峰谷电价差在档位基础上再拉宽/收窄的比例，-0.30 ~ +0.30
    degradation_weight : 循环寿命衰减惩罚权重，作用于 capex_per_kwh，0.2 ~ 3.0

``GET /api/island``：以 /api/simulate 同一套参数 + ``switch_hour``（市电跌落
时刻），基于 LP 解在该时刻的 SOC 计算离网续航、关键机架保障与母线跌落曲线。

启动（项目根目录）：
    uv run --python 3.12 --with-requirements requirements.txt \\
           --with-requirements requirements-web.txt \\
           uvicorn src.server:app --reload --port 8000
然后浏览器打开 http://127.0.0.1:8000 即可使用 src/web/ 深色工业看板。

设计约束：本模块只做「参数装配 → LP 求解 → JSON 序列化」，不复制任何
优化/物理逻辑；所有数值口径与 tests/ 覆盖的 optimizer/pue 模块严格一致。
"""
from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, List

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from src.config import (
    N_STEPS,
    STEP_HOURS,
    BatteryParams,
    Scenario,
    TariffParams,
    scenario_by_name,
)
from src.optimizer import InfeasibleError, compute_kpis, solve
from src.simulate import baseline_schedule
from src.workload import generate_cooling, generate_it_power

__all__ = ["app", "build_scenario", "rack_layout", "BATTERY_PRESETS", "TARIFF_PRESETS"]

# --------------------------------------------------------------------------
# 预设（价格档位为公开工商业典型区间的工程假设  # [INFERENCE]）
# --------------------------------------------------------------------------
BATTERY_PRESETS: Dict[str, Dict[str, float]] = {
    "2mwh": {"capacity_kwh": 2000.0, "power_kw": 500.0, "label": "2 MWh / 500 kW（标准工商业柜）"},
    "8mwh": {"capacity_kwh": 8000.0, "power_kw": 2000.0, "label": "8 MWh / 2,000 kW（园区级）"},
    "22mwh": {"capacity_kwh": 22000.0, "power_kw": 5500.0, "label": "22 MWh / 5,500 kW（替代变压器扩容）"},
}

TARIFF_PRESETS: Dict[str, Dict[str, Any]] = {
    "standard": {"label": "标准分时（谷0.30/平0.62/峰0.98/尖1.28）",
                 "prices": (0.30, 0.62, 0.98, 1.28)},
    "steep": {"label": "尖峰加剧（谷0.25/平0.60/峰1.20/尖1.65）",
              "prices": (0.25, 0.60, 1.20, 1.65)},
    "mild": {"label": "峰谷趋缓（谷0.35/平0.55/峰0.75/尖0.95）",
             "prices": (0.35, 0.55, 0.75, 0.95)},
}

# --------------------------------------------------------------------------
# 机房数字孪生布局：8 列 × 4 热通道排 = 32 机柜（确定性工程假设  # [INFERENCE]）
# gpu_dense 机架为液冷训练柜（功率密度 ≈2.5×），全部标记为 critical：
# 离网时不可中断的训练任务所在机架。
# --------------------------------------------------------------------------
_RACK_WEIGHTS = [
    2.5, 0.9, 0.7, 1.1, 0.8, 1.0, 0.6, 2.5,
    1.0, 2.5, 0.8, 0.7, 1.2, 0.6, 2.5, 0.9,
    0.7, 1.1, 2.5, 0.8, 0.6, 1.0, 0.9, 2.5,
    1.2, 0.6, 1.0, 2.5, 0.8, 0.7, 1.1, 0.9,
]


def rack_layout() -> List[Dict[str, Any]]:
    """32 机柜归一化功率权重（Σ=1）与静态元数据，供热力图/岛运算共用。"""
    total = float(sum(_RACK_WEIGHTS))
    racks = []
    for i, w in enumerate(_RACK_WEIGHTS):
        racks.append({
            "id": "R{:02d}".format(i + 1),
            "row": i // 8,
            "col": i % 8,
            "weight": round(w / total, 5),
            "gpu_dense": w >= 2.0,
            "critical": w >= 2.0,
        })
    return racks


def build_scenario(
    scenario: str,
    spike_multiplier: float,
    battery_key: str,
    tariff_key: str,
    c_rate: float = 0.25,
    price_spread: float = 0.0,
    degradation_weight: float = 1.0,
) -> Scenario:
    """从白名单参数装配实时情景（深拷贝，不污染 config 默认工厂）。"""
    if scenario not in ("baseline_day", "transient_spike", "extreme_peak"):
        raise ValueError("unknown scenario: {}".format(scenario))
    if battery_key not in BATTERY_PRESETS:
        raise ValueError("unknown battery preset: {}".format(battery_key))
    if tariff_key not in TARIFF_PRESETS:
        raise ValueError("unknown tariff preset: {}".format(tariff_key))
    if not (0.5 <= float(spike_multiplier) <= 4.0):
        raise ValueError("spike_multiplier 必须落在 [0.5, 4.0]")
    if not (0.2 <= float(c_rate) <= 1.0):
        raise ValueError("c_rate 必须落在 [0.2, 1.0]")
    if not (-0.30 <= float(price_spread) <= 0.30):
        raise ValueError("price_spread 必须落在 [-0.30, 0.30]")
    if not (0.2 <= float(degradation_weight) <= 3.0):
        raise ValueError("degradation_weight 必须落在 [0.2, 3.0]")

    sc = copy.deepcopy(scenario_by_name(scenario))
    sc.datacenter.it_peak_kw = sc.datacenter.it_base_kw + (
        sc.datacenter.it_peak_kw - sc.datacenter.it_base_kw
    ) * float(spike_multiplier)

    preset = BATTERY_PRESETS[battery_key]
    power_kw = preset["capacity_kwh"] * float(c_rate)
    base_bat = sc.battery
    sc.battery = BatteryParams(
        capacity_kwh=preset["capacity_kwh"],
        p_charge_max_kw=power_kw,
        p_discharge_max_kw=power_kw,
        soc_min=base_bat.soc_min,
        soc_max=base_bat.soc_max,
        soc_init=base_bat.soc_init,
        eta_charge=base_bat.eta_charge,
        eta_discharge=base_bat.eta_discharge,
        cycle_life=base_bat.cycle_life,
        capex_per_kwh=base_bat.capex_per_kwh * float(degradation_weight),
        om_cost_per_kwh=base_bat.om_cost_per_kwh,
    )

    v, f, p, s = TARIFF_PRESETS[tariff_key]["prices"]
    k = 1.0 + float(price_spread)
    sc.tariff = TariffParams(
        valley_price=f + (v - f) * k,
        flat_price=f,
        peak_price=f + (p - f) * k,
        sharp_price=f + (s - f) * k,
    )
    return sc


# --------------------------------------------------------------------------
# 仿真计算
# --------------------------------------------------------------------------
def run_simulate(sc: Scenario) -> Dict[str, Any]:
    """LP 求解 + KPI 汇总；不可行时返回结构化 infeasible 载荷。"""
    it = generate_it_power(sc)
    cool = generate_cooling(it, sc)
    prices = sc.price_series()
    hours = [round(t * STEP_HOURS, 2) for t in range(N_STEPS)]

    base = baseline_schedule(sc, it, cool)
    kpi_base = compute_kpis(base, sc, prices).as_dict()

    payload: Dict[str, Any] = {
        "meta": {
            "scenario": sc.name,
            "grid_limit_kw": float(sc.datacenter.grid_connection_kw),
            "it_peak_kw": round(float(sc.datacenter.it_peak_kw), 1),
            "battery": {"capacity_kwh": float(sc.battery.capacity_kwh),
                        "power_kw": float(sc.battery.p_discharge_max_kw)},
            "n_steps": N_STEPS,
            "step_hours": STEP_HOURS,
        },
        "thermal": {
            "racks": rack_layout(),
            "pue_design_band": [1.15, 1.28],
            "pue_target": float(sc.datacenter.pue_target),
            "cold_aisle_setpoint_c": 18.0,   # [INFERENCE] 冷通道送风设计点
        },
        "series": {
            "hours": hours,
            "it_kw": np.round(it, 1).tolist(),
            "cooling_kw": np.round(cool, 1).tolist(),
            "grid_base_kw": np.round(base.grid_import_kw, 1).tolist(),
            "soc_pct": None,
            "charge_kw": None,
            "discharge_kw": None,
            "grid_opt_kw": None,
            "pue_base": None,
            "pue_opt": None,
        },
        "kpis": {
            "baseline_peak_kw": round(kpi_base["peak_grid_kw"], 1),
            "baseline_total_cost": round(kpi_base["total_cost"], 1),
        },
    }

    t0 = time.time()
    try:
        opt = solve(sc, it, cool)
    except InfeasibleError as exc:
        payload["status"] = "infeasible"
        payload["message"] = str(exc)
        return payload
    solve_ms = (time.time() - t0) * 1000.0

    kpi_opt = compute_kpis(opt, sc, prices).as_dict()
    dc, bat = sc.datacenter, sc.battery

    ups = dc.ups_loss_ratio * (it + cool)
    pue_base = (it + cool + ups) / it
    bat_loss = (opt.charge_kw * (1.0 - bat.eta_charge)
                + opt.discharge_kw * (1.0 / bat.eta_discharge - 1.0))
    pue_opt = (it + cool + ups + bat_loss) / it

    s = payload["series"]
    s["grid_opt_kw"] = np.round(opt.grid_import_kw, 1).tolist()
    s["charge_kw"] = np.round(opt.charge_kw, 1).tolist()
    s["discharge_kw"] = np.round(opt.discharge_kw, 1).tolist()
    s["soc_pct"] = np.round(opt.soc * 100.0, 2).tolist()
    s["pue_base"] = np.round(pue_base, 4).tolist()
    s["pue_opt"] = np.round(pue_opt, 4).tolist()

    payload["status"] = "optimal"
    payload["kpis"].update({
        "peak_grid_kw": round(kpi_opt["peak_grid_kw"], 1),
        "peak_shaved_ratio": round(kpi_opt["peak_shaved_ratio"], 4),
        "total_cost": round(kpi_opt["total_cost"], 1),
        "saving_yuan": round(kpi_base["total_cost"] - kpi_opt["total_cost"], 1),
        "saving_pct": round(
            (kpi_base["total_cost"] - kpi_opt["total_cost"])
            / kpi_base["total_cost"] * 100.0, 2) if kpi_base["total_cost"] > 0 else 0.0,
        "demand_saving_yuan": round(kpi_base["demand_cost"] - kpi_opt["demand_cost"], 1),
        "degradation_cost": round(kpi_opt["degradation_cost"], 1),
        "electricity_cost": round(kpi_opt["electricity_cost"], 1),
        "load_factor": round(kpi_opt["load_factor"], 3),
        "avg_pue_base": round(kpi_base["avg_pue"], 4),
        "avg_pue_opt": round(kpi_opt["avg_pue"], 4),
        "delta_pue": round(kpi_opt["avg_pue"] - kpi_base["avg_pue"], 4),
        "solve_ms": round(solve_ms, 1),
    })
    return payload


# --------------------------------------------------------------------------
# 离网应急（Island Mode）仿真
# --------------------------------------------------------------------------
SWITCHOVER_MS = 10.0  # [INFERENCE] 钠电 PCS 无缝切换指标（对标 GB/T 储能并网规范）


def run_island(sc: Scenario, switch_hour: float) -> Dict[str, Any]:
    """市电跌落 → 切岛的供电保障与续航估算。

    口径：取 LP 最优解在 ``switch_hour`` 步末的 SOC 作为切岛初值；离网后
    只保障 critical（GPU 液冷训练）机架，非关键负荷主动甩负荷。
    续航 = 可放电量(交流侧) ÷ 关键负荷，且受电池额定功率封顶。
    """
    if not (0.0 <= float(switch_hour) < N_STEPS * STEP_HOURS):
        raise ValueError("switch_hour 必须落在 [0, 24)")

    it = generate_it_power(sc)
    cool = generate_cooling(it, sc)
    idx = min(int(round(float(switch_hour) / STEP_HOURS)), N_STEPS - 1)

    warning = None
    try:
        opt = solve(sc, it, cool)
        soc_at = float(opt.soc[idx])
        grid_at = float(opt.grid_import_kw[idx])
    except InfeasibleError:
        # 削峰不可行的配置下，储能仍可作纯应急电源：按初始 SOC 评估
        soc_at = float(sc.battery.soc_init)
        grid_at = float(it[idx] + cool[idx])
        warning = "该配置下 LP 削峰不可行，岛网按储能初始 SOC 估算"

    bat, dc = sc.battery, sc.datacenter
    racks = rack_layout()
    crit_w = sum(r["weight"] for r in racks if r["critical"])
    total_it = float(it[idx])
    critical_kw = total_it * crit_w
    shed_kw = total_it - critical_kw

    usable_kwh = max(0.0, (soc_at - bat.soc_min) * bat.capacity_kwh * bat.eta_discharge)
    load_kw = min(critical_kw, bat.p_discharge_max_kw)
    power_capped = critical_kw > bat.p_discharge_max_kw + 1e-6
    if power_capped:
        load_kw = bat.p_discharge_max_kw
        warning = (warning + "；" if warning else "") + \
            "关键负荷超出电池额定功率，仅能保障部分机架"
    endurance_h = usable_kwh / load_kw if load_kw > 0 else 0.0

    minutes, soc_series, load_series = [], [], []
    n_pts = int(min(240.0, endurance_h * 60.0)) + 1
    soc = soc_at
    for k in range(n_pts):
        minutes.append(k)
        soc_series.append(round(soc * 100.0, 2))
        load_series.append(round(load_kw, 1))
        soc -= (load_kw / bat.eta_discharge) * (1.0 / 60.0) / bat.capacity_kwh

    return {
        "status": "island",
        "warning": warning,
        "switch_hour": round(idx * STEP_HOURS, 2),
        "switchover_ms": SWITCHOVER_MS,
        "grid_load_at_switch_kw": round(grid_at, 1),
        "soc_at_switch_pct": round(soc_at * 100.0, 2),
        "soc_min_pct": round(bat.soc_min * 100.0, 2),
        "usable_energy_kwh": round(usable_kwh, 1),
        "critical_racks": sum(1 for r in racks if r["critical"]),
        "critical_load_kw": round(critical_kw, 1),
        "served_load_kw": round(load_kw, 1),
        "shed_load_kw": round(shed_kw + max(0.0, critical_kw - load_kw), 1),
        "endurance_min": round(endurance_h * 60.0, 1),
        "drain": {"minutes": minutes, "soc_pct": soc_series, "load_kw": load_series},
    }


# --------------------------------------------------------------------------
# FastAPI 应用
# --------------------------------------------------------------------------
app = FastAPI(title="钠电 × AIDC 削峰填谷仿真控制台", version="1.0")


@app.get("/api/simulate")
def api_simulate(
    scenario: str = Query("transient_spike"),
    spike_multiplier: float = Query(1.0, ge=0.5, le=4.0),
    battery: str = Query("2mwh"),
    tariff: str = Query("standard"),
    c_rate: float = Query(0.25, ge=0.2, le=1.0),
    price_spread: float = Query(0.0, ge=-0.30, le=0.30),
    degradation_weight: float = Query(1.0, ge=0.2, le=3.0),
) -> Dict[str, Any]:
    try:
        sc = build_scenario(scenario, spike_multiplier, battery, tariff,
                            c_rate, price_spread, degradation_weight)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run_simulate(sc)


@app.get("/api/island")
def api_island(
    scenario: str = Query("transient_spike"),
    spike_multiplier: float = Query(1.0, ge=0.5, le=4.0),
    battery: str = Query("2mwh"),
    tariff: str = Query("standard"),
    c_rate: float = Query(0.25, ge=0.2, le=1.0),
    price_spread: float = Query(0.0, ge=-0.30, le=0.30),
    degradation_weight: float = Query(1.0, ge=0.2, le=3.0),
    switch_hour: float = Query(14.0, ge=0.0, lt=24.0),
) -> Dict[str, Any]:
    try:
        sc = build_scenario(scenario, spike_multiplier, battery, tariff,
                            c_rate, price_spread, degradation_weight)
        return run_island(sc, switch_hour)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/presets")
def api_presets() -> Dict[str, Any]:
    return {"battery": BATTERY_PRESETS, "tariff": TARIFF_PRESETS,
            "scenarios": ["baseline_day", "transient_spike", "extreme_peak"],
            "ranges": {"c_rate": [0.2, 1.0], "price_spread": [-0.30, 0.30],
                       "degradation_weight": [0.2, 3.0]}}


_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
