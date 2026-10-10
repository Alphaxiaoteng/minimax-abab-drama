"""轻量级仿真服务端 —— FastAPI + 静态看板。

接口
----
``GET /api/simulate``：按查询参数实时构建情景并调用 ``src.optimizer.solve``
求解 LP，返回 96 步调度序列与 KPI（JSON）。

参数（均有白名单/区间校验，非法输入直接 422）：
    scenario          : baseline_day | transient_spike | extreme_peak
    spike_multiplier  : 算力尖峰倍率，作用于 it_peak_kw，0.5 ~ 4.0
    battery           : 储能配置预设 key（见 BATTERY_PRESETS）
    tariff            : 分时电价方案 key（见 TARIFF_PRESETS）

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

__all__ = ["app", "build_scenario", "BATTERY_PRESETS", "TARIFF_PRESETS"]

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


def build_scenario(
    scenario: str,
    spike_multiplier: float,
    battery_key: str,
    tariff_key: str,
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

    sc = copy.deepcopy(scenario_by_name(scenario))
    sc.datacenter.it_peak_kw = sc.datacenter.it_base_kw + (
        sc.datacenter.it_peak_kw - sc.datacenter.it_base_kw
    ) * float(spike_multiplier)

    preset = BATTERY_PRESETS[battery_key]
    base_bat = sc.battery
    sc.battery = BatteryParams(
        capacity_kwh=preset["capacity_kwh"],
        p_charge_max_kw=preset["power_kw"],
        p_discharge_max_kw=preset["power_kw"],
        soc_min=base_bat.soc_min,
        soc_max=base_bat.soc_max,
        soc_init=base_bat.soc_init,
        eta_charge=base_bat.eta_charge,
        eta_discharge=base_bat.eta_discharge,
        cycle_life=base_bat.cycle_life,
        capex_per_kwh=base_bat.capex_per_kwh,
        om_cost_per_kwh=base_bat.om_cost_per_kwh,
    )

    v, f, p, s = TARIFF_PRESETS[tariff_key]["prices"]
    sc.tariff = TariffParams(valley_price=v, flat_price=f, peak_price=p, sharp_price=s)
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
# FastAPI 应用
# --------------------------------------------------------------------------
app = FastAPI(title="钠电 × AIDC 削峰填谷仿真控制台", version="1.0")


@app.get("/api/simulate")
def api_simulate(
    scenario: str = Query("transient_spike"),
    spike_multiplier: float = Query(1.0, ge=0.5, le=4.0),
    battery: str = Query("2mwh"),
    tariff: str = Query("standard"),
) -> Dict[str, Any]:
    try:
        sc = build_scenario(scenario, spike_multiplier, battery, tariff)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run_simulate(sc)


@app.get("/api/presets")
def api_presets() -> Dict[str, Any]:
    return {"battery": BATTERY_PRESETS, "tariff": TARIFF_PRESETS,
            "scenarios": ["baseline_day", "transient_spike", "extreme_peak"]}


_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
