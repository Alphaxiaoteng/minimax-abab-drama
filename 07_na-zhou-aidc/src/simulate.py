"""端到端仿真编排 —— 三种调度策略的对比。

本模块是**唯一**把 workload / battery / tariff / optimizer / pue 串起来的地方，
因此也是报告中所有数字的唯一来源。其他模块只提供零件，不做编排。

对比的三条策略
--------------
1. ``baseline``  无储能。电网功率 = IT + 制冷 + UPS 损耗，是全部收益的基准。
2. ``greedy``    规则型削峰填谷（无优化）：谷段满功率充电，峰/尖峰段满功率放电，
                 其余时段待机。代表工业现场最常见的"定时充放"朴素做法，
                 用来证明线性规划相对规则策略的增量价值。
3. ``optimal``   线性规划全局最优（见 ``src/optimizer.py``）。

三方对比的意义：只有把 ``greedy`` 放在中间，才能证明「LP 不是把参数调到好看，
而是真的比人在现场拍脑袋的规则强多少」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from src.battery import simulate_soc, throughput_cost_per_kwh
from src.config import (
    GRID_CO2_FACTOR,
    N_STEPS,
    STEP_HOURS,
    Scenario,
    default_scenarios,
    price_level,
    scenario_by_name,
)
from src.optimizer import compute_kpis, solve
from src.pue import annualized_pue, cooling_energy_share, instantaneous_pue, pue_quantiles
from src.tariff import demand_charge, energy_cost, tou_breakdown
from src.workload import generate_cooling, generate_it_power, spike_stats

__all__ = [
    "SimulationResult",
    "run_scenario",
    "run_all",
    "baseline_schedule",
    "greedy_schedule",
    "optimal_schedule",
    "summary_table",
]

_TOL = 1e-6


@dataclass
class SimulationResult:
    """一个情景下三种策略的完整结果。"""

    scenario: Scenario
    it_power: np.ndarray
    cooling: np.ndarray
    schedules: Dict[str, Any]           # name -> Schedule
    kpis: Dict[str, Dict[str, Any]]     # name -> KPI dict
    pue_stats: Dict[str, Any]           # 额外 PUE 分析（含对比与分解）
    load_stats: Dict[str, float]

    @property
    def baseline(self) -> Any:
        return self.schedules["baseline"]

    @property
    def optimal(self) -> Any:
        return self.schedules["optimal"]

    @property
    def greedy(self) -> Any:
        return self.schedules["greedy"]

    def comparison(self) -> Dict[str, float]:
        """最优策略相对基线的收益汇总（元/日、kW、kWh、kg）。"""
        b, o = self.kpis["baseline"], self.kpis["optimal"]
        g = self.kpis["greedy"]
        return {
            "cost_saving_yuan": b["total_cost"] - o["total_cost"],
            "cost_saving_pct": (
                (b["total_cost"] - o["total_cost"]) / b["total_cost"] * 100.0
                if b["total_cost"] > 0 else 0.0
            ),
            "lp_vs_greedy_yuan": g["total_cost"] - o["total_cost"],
            "lp_vs_greedy_pct": (
                (g["total_cost"] - o["total_cost"]) / g["total_cost"] * 100.0
                if g["total_cost"] > 0 else 0.0
            ),
            "peak_shaved_kw": b["peak_grid_kw"] - o["peak_grid_kw"],
            "peak_shaved_pct": o["peak_shaved_ratio"] * 100.0,
            "grid_energy_saved_kwh": b["extra"].get("grid_energy_kwh", 0.0)
            - o["extra"].get("grid_energy_kwh", 0.0),
            "co2_saved_kg": o["co2_saved_kg"],
            "load_factor_gain": o["load_factor"] - b["load_factor"],
        }


# --------------------------------------------------------------------------
# 三种策略
# --------------------------------------------------------------------------
def baseline_schedule(scenario: Scenario, it_power: np.ndarray,
                      cooling: Optional[np.ndarray] = None) -> Any:
    """无储能基线：电网全额供电。"""
    from src.types import Schedule

    if cooling is None:
        cooling = generate_cooling(it_power, scenario)
    ups = scenario.datacenter.ups_loss_ratio * (it_power + cooling)
    grid = it_power + cooling + ups
    zeros = np.zeros(N_STEPS, dtype=float)
    soc = np.full(N_STEPS, scenario.battery.soc_init, dtype=float)
    return Schedule(
        strategy="baseline",
        charge_kw=zeros.copy(),
        discharge_kw=zeros.copy(),
        soc=soc,
        grid_import_kw=grid,
        it_power_kw=np.asarray(it_power, dtype=float).copy(),
        cooling_kw=np.asarray(cooling, dtype=float).copy(),
        objective_value=0.0,
        status="baseline",
    )


def greedy_schedule(scenario: Scenario, it_power: np.ndarray,
                    cooling: Optional[np.ndarray] = None) -> Any:
    """规则型定时充放：谷段满充，峰/尖峰段满放，其余待机。

    这是一个**有物理约束保护**的贪心：每一步都按当前 SOC 与功率上限裁剪，
    保证 SOC 不越界；因此它一定可行，只是远非最优（谷段充进来的电未必
    刚好覆盖峰段需求，SOC 可能在关键尖峰还没到就用完）。
    """
    from src.types import Schedule

    if cooling is None:
        cooling = generate_cooling(it_power, scenario)
    dc, bat = scenario.datacenter, scenario.battery
    prices = scenario.price_series()

    it = np.asarray(it_power, dtype=float)
    cool = np.asarray(cooling, dtype=float)
    ups = dc.ups_loss_ratio * (it + cool)
    load = it + cool + ups

    charge = np.zeros(N_STEPS, dtype=float)
    discharge = np.zeros(N_STEPS, dtype=float)
    soc = np.empty(N_STEPS, dtype=float)
    prev = float(bat.soc_init)

    # 规则策略的公平性要求：必须与 LP 一样受日循环约束，否则它会"卖掉"初始电量
    # 制造虚假收益。因此中途一旦为下一尖峰预留了 SOC，最后必须把能量补回来。
    level_of = [price_level(t * STEP_HOURS) for t in range(N_STEPS)]
    last_peak_step = max(
        (t for t in range(N_STEPS) if level_of[t] in ("peak", "sharp")),
        default=-1,
    )

    for t in range(N_STEPS):
        level = level_of[t]
        # 规则策略的铁律：充电只能在并网点"有富余"时进行。
        # 若当前负荷已经贴着或超过限额，任何充电都会把峰值顶得更高——
        # 这正是规则策略相对 LP 的典型缺陷来源，必须如实保留而不能偷偷放宽。
        headroom_kw = max(0.0, dc.facility_limit_kw - load[t])
        if level == "valley":
            usable_kw = max(
                0.0,
                (bat.soc_max - prev) * bat.capacity_kwh
                / (bat.eta_charge * STEP_HOURS),
            )
            p = min(bat.p_charge_max_kw, usable_kw, headroom_kw)
            charge[t] = p
            prev += bat.eta_charge * p * STEP_HOURS / bat.capacity_kwh
        elif level in ("peak", "sharp"):
            # 峰段放掉可放的（受 SOC 下限与功率上限约束）
            usable_kw = max(
                0.0,
                (prev - bat.soc_min) * bat.capacity_kwh * bat.eta_discharge
                / STEP_HOURS,
            )
            p = min(bat.p_discharge_max_kw, usable_kw)
            discharge[t] = p
            prev -= p * STEP_HOURS / (bat.eta_discharge * bat.capacity_kwh)
        else:
            # 平段：SOC 偏低则补到 50%，为后续尖峰预留裕度
            target = 0.5
            if prev < target:
                want = min(
                    bat.p_charge_max_kw,
                    max(0.0, (target - prev) * bat.capacity_kwh
                        / (bat.eta_charge * STEP_HOURS)),
                )
                p = min(want, headroom_kw)
                charge[t] = p
                prev += bat.eta_charge * p * STEP_HOURS / bat.capacity_kwh
        soc[t] = prev

    # 日循环收尾：最后一次峰段之后，把 SOC 回补到初始值（与 LP 终端约束同口径）。
    # 只在平/谷段补电，且不超过并网点限额，保证规则策略不会靠"吃掉"起始电量获利。
    if last_peak_step >= 0:
        deficit_kwh = (bat.soc_init - prev) * bat.capacity_kwh
        for t in range(last_peak_step + 1, N_STEPS):
            if deficit_kwh <= 1e-9:
                break
            if level_of[t] in ("peak", "sharp"):
                continue
            p = min(
                bat.p_charge_max_kw,
                max(0.0, dc.facility_limit_kw - load[t]),
                deficit_kwh / (bat.eta_charge * STEP_HOURS),
                max(0.0, (bat.soc_max - prev) * bat.capacity_kwh
                    / (bat.eta_charge * STEP_HOURS)),
            )
            if p <= 1e-9:
                continue
            charge[t] += p
            prev += bat.eta_charge * p * STEP_HOURS / bat.capacity_kwh
            deficit_kwh -= bat.eta_charge * p * STEP_HOURS
            soc[t] = prev
        # 收尾段的 SOC 轨迹需要向后传递，避免数组里残留旧值
        for t in range(last_peak_step + 1, N_STEPS):
            if t == 0:
                continue
            if soc[t] == 0.0:
                soc[t] = soc[t - 1]

    grid = load + charge - discharge
    return Schedule(
        strategy="greedy",
        charge_kw=charge,
        discharge_kw=discharge,
        soc=soc,
        grid_import_kw=grid,
        it_power_kw=it.copy(),
        cooling_kw=cool.copy(),
        objective_value=0.0,
        status="greedy",
    )


def optimal_schedule(scenario: Scenario, it_power: np.ndarray,
                     cooling: Optional[np.ndarray] = None,
                     reserve_margin_kw: float = 0.0) -> Any:
    """线性规划最优调度（直接委托 optimizer）。"""
    return solve(scenario, it_power, cooling, reserve_margin_kw=reserve_margin_kw)


# --------------------------------------------------------------------------
# 编排
# --------------------------------------------------------------------------
def _pue_block(scenario: Scenario, res_it: np.ndarray, res_cool: np.ndarray,
               sched_base: Any, sched_opt: Any) -> Dict[str, Any]:
    """PUE 分析汇总。"""
    dc = scenario.datacenter
    pue_base = instantaneous_pue(res_it, res_cool, dc.ups_loss_ratio)
    pue_opt = instantaneous_pue(res_it, res_cool, dc.ups_loss_ratio)
    return {
        "baseline": {
            "series": pue_base,
            "quantiles": pue_quantiles(pue_base),
            "avg": float(np.mean(pue_base)),
            "max": float(np.max(pue_base)),
            "annualized": annualized_pue(pue_base),
        },
        "cooling_share": cooling_energy_share(res_it, res_cool, dc.ups_loss_ratio),
        "with_vs_without_storage": None,  # 由 report 层填写（需要两条 Schedule）
        "pue_target": dc.pue_target,
        "series_base": pue_base,
        "series_opt": pue_opt,
    }


def run_scenario(scenario: Scenario,
                 include_greedy: bool = True,
                 reserve_margin_kw: float = 0.0) -> SimulationResult:
    """跑完一个情景的全部策略并汇总。"""
    it = generate_it_power(scenario)
    cool = generate_cooling(it, scenario)
    prices = scenario.price_series()

    schedules: Dict[str, Any] = {}
    kpis: Dict[str, Dict[str, Any]] = {}

    base = baseline_schedule(scenario, it, cool)
    schedules["baseline"] = base
    kpis["baseline"] = _finalize_kpis(scenario, base, prices, is_baseline=True)

    if include_greedy:
        greedy = greedy_schedule(scenario, it, cool)
        schedules["greedy"] = greedy
        kpis["greedy"] = _finalize_kpis(scenario, greedy, prices, is_baseline=False)

    opt = optimal_schedule(scenario, it, cool, reserve_margin_kw=reserve_margin_kw)
    schedules["optimal"] = opt
    kpis["optimal"] = _finalize_kpis(scenario, opt, prices, is_baseline=False)

    # 削峰比例 / 套利节省 / 碳减排统一相对基线口径，避免各模块各算一套、口径漂移
    base_peak = kpis["baseline"]["peak_grid_kw"]
    base_cost = kpis["baseline"]["total_cost"]
    base_grid_kwh = kpis["baseline"]["extra"]["grid_energy_kwh"]
    base_discharge_kwh = kpis["baseline"]["extra"]["discharge_throughput_kwh"]

    for name in schedules:
        k = kpis[name]
        k["peak_shaved_ratio"] = (
            1.0 - k["peak_grid_kw"] / base_peak if base_peak > 0 else 0.0
        )
        k["arbitrage_saving"] = base_cost - k["electricity_cost"] - k["demand_cost"]
        saved_kwh = base_grid_kwh - k["extra"]["grid_energy_kwh"]
        k["saved_energy_kwh"] = saved_kwh
        # 诚实口径：储能往返损耗存在，绝大部分情况下"购电量"反而上升，
        # 因此 saved_kwh 常为负。这里不粉饰：CO2 只在真正少买电时才算减排，
        # 少买电为负则记为负（= 多排），由报告显式解释。
        k["co2_saved_kg"] = saved_kwh * GRID_CO2_FACTOR
        # 本轮放电吞吐与基线（0）之差，用于报告中的电池利用率
        k["extra"]["discharge_delta_kwh"] = (
            k["extra"]["discharge_throughput_kwh"] - base_discharge_kwh
        )

    pue_block = _pue_block(scenario, it, cool, base, opt)

    result = SimulationResult(
        scenario=scenario,
        it_power=it,
        cooling=cool,
        schedules=schedules,
        kpis=kpis,
        pue_stats=pue_block,
        load_stats=spike_stats(it, scenario.datacenter.it_base_kw),
    )
    return result


def _finalize_kpis(scenario: Scenario, sched: Any, prices: np.ndarray,
                   is_baseline: bool) -> Dict[str, Any]:
    """在 optimizer.compute_kpis 之上补齐编排层独有字段（电量口径等）。"""
    if is_baseline:
        # 无储能时 compute_kpis 仍可用（charge/discharge 为 0）
        kpi_obj = compute_kpis(sched, scenario, prices)
    else:
        kpi_obj = compute_kpis(sched, scenario, prices)
    d = kpi_obj.as_dict()

    dc = scenario.datacenter
    grid_kwh = float(np.sum(sched.grid_import_kw) * STEP_HOURS)
    it_kwh = float(np.sum(sched.it_power_kw) * STEP_HOURS)
    cool_kwh = float(np.sum(sched.cooling_kw) * STEP_HOURS)
    ups_kwh = dc.ups_loss_ratio * (it_kwh + cool_kwh)
    thru_kwh = float(np.sum(sched.discharge_kw) * STEP_HOURS)

    d["extra"] = {
        "grid_energy_kwh": grid_kwh,
        "it_energy_kwh": it_kwh,
        "cooling_energy_kwh": cool_kwh,
        "ups_loss_kwh": ups_kwh,
        "discharge_throughput_kwh": thru_kwh,
        "battery_round_trip_loss_kwh": thru_kwh / scenario.battery.round_trip_efficiency
        - thru_kwh,
    }
    return d


def run_all(include_greedy: bool = True,
            reserve_margin_kw: float = 0.0) -> List[SimulationResult]:
    """跑完全部默认情景。"""
    return [
        run_scenario(s, include_greedy=include_greedy,
                     reserve_margin_kw=reserve_margin_kw)
        for s in default_scenarios()
    ]


def summary_table(results: List[SimulationResult]) -> List[Dict[str, Any]]:
    """把多情景结果压平成表格行，供 report 直接渲染。"""
    rows: List[Dict[str, Any]] = []
    for r in results:
        cmp_ = r.comparison()
        for name in ("baseline", "greedy", "optimal"):
            if name not in r.kpis:
                continue
            k = r.kpis[name]
            rows.append({
                "scenario": r.scenario.name,
                "strategy": name,
                "total_cost": k["total_cost"],
                "electricity_cost": k["electricity_cost"],
                "demand_cost": k["demand_cost"],
                "degradation_cost": k["degradation_cost"],
                "peak_grid_kw": k["peak_grid_kw"],
                "peak_shaved_ratio": k["peak_shaved_ratio"],
                "load_factor": k["load_factor"],
                "avg_pue": k["avg_pue"],
                "co2_saved_kg": k["co2_saved_kg"],
            })
    return rows
