"""削峰填谷线性规划（LP）求解器 —— PuLP + CBC。

LP 公式（供报告引用）
======================
决策变量 (t = 0..T-1, T=96, dt=STEP_HOURS=0.25h)：
    charge[t]    ∈ [0, p_charge_max]      储能充电功率 (kW)
    discharge[t] ∈ [0, p_dis_max]         储能放电功率 (kW)
    soc[t]       ∈ [soc_min, soc_max]     步末 SOC（0~1，无量纲）
    grid[t]      ∈ [0, grid_limit]        电网取电功率 (kW)
    peak         >= 0                     最大并网点取电 (kW)  —— 需量计费标量

目标（最小化，单位：元/日）：
    min Σ_t price[t]·grid[t]·dt
      + peak · demand_per_kw / 30
      + Σ_t discharge[t] · dt · c_throughput

约束：
    (1) 功率平衡: grid[t] + discharge[t] − charge[t] = load[t]
        其中 load[t] = it[t] + cool[t] + ups_loss[t]，
        ups_loss[t] = ups_loss_ratio · (it[t] + cool[t])
    (2) 并网硬限: grid[t] ≤ grid_connection_kw − reserve_margin_kw
    (3) SOC 递推（步末定义）：
        soc[0] = soc_init + (η_c·charge[0] − discharge[0]/η_d)·dt / capacity_kwh
        soc[t] = soc[t-1] + (η_c·charge[t] − discharge[t]/η_d)·dt / capacity_kwh, t≥1
    (4) SOC 边界: soc_min ≤ soc[t] ≤ soc_max
    (5) 循环日终端: soc[T-1] ≥ soc_init（enforce_terminal_soc=True 时）
    (6) 峰值上界: peak ≥ grid[t] ∀t

退化成本约定
------------
老化只计**放电吞吐**（元/kWh = capex_per_kwh/cycle_life + om_cost_per_kwh，
由 `src.battery.throughput_cost_per_kwh` 提供）。充电不重复计老化；
充放电效率损失通过 SOC 递推自然反映到电量成本上。

为何纯 LP（无二进制互斥变量）
------------------------------
对任意步骤 t，若同时开启 charge[t]>0 且 discharge[t]>0，
    Δgrid[t] = charge[t] − discharge[t]   只取决于净值；
    Δsoc[t]  = (η_c·charge − discharge/η_d)·dt/cap
而目标额外项 c_throughput·discharge·dt ≥ 0，且 η_c·η_d < 1 ⇒
内部循环既无「降低 grid」的额外收益，又要付吞吐与效率双重成本。
因此 LP 顶点解自动满足互补条件 charge[t]·discharge[t] = 0，
无需 LpBinary 互斥约束（tests/test_optimizer.py 数值验证）。

模块常量
--------
GRID_CO2_FACTOR : float = 0.581
    中国区域电网平均碳排放因子 kgCO2/kWh。  # [INFERENCE]
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pulp

from src.battery import throughput_cost_per_kwh
from src.config import N_STEPS, STEP_HOURS, Scenario
from src.types import KPIs, Schedule

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
GRID_CO2_FACTOR: float = 0.581  # kgCO2/kWh  [INFERENCE]

# 进程级求解器耗时遥测（非 LP 组成部分）：scenario.name → solve 墙钟秒数。
# 仅用于 KPI 报告；多进程/多线程环境下每个进程各自维护一份。
LAST_SOLVE_SECONDS: Dict[str, float] = {}


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------
class InfeasibleError(RuntimeError):
    """LP 不可行：含违规步骤与所需 kW 说明。"""
    pass


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _total_load_kw(scenario: Scenario, it: np.ndarray, cool: np.ndarray) -> np.ndarray:
    """每步总负荷 = it + cool + ups_loss，供功率平衡约束使用。"""
    ups = float(scenario.datacenter.ups_loss_ratio) * (it + cool)
    return it + cool + ups


# --------------------------------------------------------------------------
# build_model
# --------------------------------------------------------------------------
def build_model(
    scenario: Scenario,
    it_power_kw: np.ndarray,
    cooling_kw: np.ndarray,
    price_series_arr: np.ndarray,
    reserve_margin_kw: float = 0.0,
    enforce_terminal_soc: bool = True,
) -> Tuple[pulp.LpProblem, Dict[str, Any]]:
    """构建削峰填谷 LP。

    Parameters
    ----------
    scenario : Scenario
    it_power_kw, cooling_kw, price_series_arr : shape (N_STEPS,) float
    reserve_margin_kw : N-1 备用裕度（kW），从 grid_connection_kw 中扣除。
    enforce_terminal_soc : True ⇒ 终端 soc[T-1] ≥ soc_init（循环日）。

    Returns
    -------
    (LpProblem, vars_dict)
        vars_dict 键：``charge`` / ``discharge`` / ``soc`` / ``grid_import``
        （每个是 ``Dict[int, LpVariable]``）与 ``peak_kw``（``LpVariable``）。
    """
    it = np.asarray(it_power_kw, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)
    prices = np.asarray(price_series_arr, dtype=float)

    if it.shape != (N_STEPS,):
        raise ValueError("it_power_kw 形状须为 ({},)，实际 {}".format(N_STEPS, it.shape))
    if cool.shape != (N_STEPS,):
        raise ValueError("cooling_kw 形状须为 ({},)，实际 {}".format(N_STEPS, cool.shape))
    if prices.shape != (N_STEPS,):
        raise ValueError("price_series 形状须为 ({},)，实际 {}".format(N_STEPS, prices.shape))

    bat = scenario.battery
    dc = scenario.datacenter

    dt = float(STEP_HOURS)
    cap = float(bat.capacity_kwh)
    eta_c = float(bat.eta_charge)
    eta_d = float(bat.eta_discharge)
    soc_min = float(bat.soc_min)
    soc_max = float(bat.soc_max)
    soc_init = float(bat.soc_init)
    p_chg = float(bat.p_charge_max_kw)
    p_dis = float(bat.p_discharge_max_kw)

    grid_limit = float(dc.grid_connection_kw) - float(reserve_margin_kw)
    if grid_limit <= 0.0:
        raise ValueError(
            "有效并网限额 grid_connection_kw({:.1f}) − reserve({:.1f}) = {:.1f} ≤ 0".format(
                dc.grid_connection_kw, reserve_margin_kw, grid_limit
            )
        )

    demand_per_kw = float(dc.demand_charge_per_kw)
    cost_throughput = throughput_cost_per_kwh(bat)

    load = _total_load_kw(scenario, it, cool)

    prob = pulp.LpProblem("na_zhou_aidc", pulp.LpMinimize)
    T = N_STEPS

    # ---- 变量 ----
    charge = {t: pulp.LpVariable("charge_{}".format(t), lowBound=0.0, upBound=p_chg) for t in range(T)}
    discharge = {t: pulp.LpVariable("discharge_{}".format(t), lowBound=0.0, upBound=p_dis) for t in range(T)}
    soc = {t: pulp.LpVariable("soc_{}".format(t), lowBound=soc_min, upBound=soc_max) for t in range(T)}
    grid = {t: pulp.LpVariable("grid_{}".format(t), lowBound=0.0, upBound=grid_limit) for t in range(T)}
    peak_var = pulp.LpVariable("peak_kw", lowBound=0.0, upBound=grid_limit)

    vars_dict = {
        "charge": charge,
        "discharge": discharge,
        "soc": soc,
        "grid_import": grid,
        "peak_kw": peak_var,
    }

    # ---- 约束 ----
    for t in range(T):
        # (1) 功率平衡
        prob += grid[t] + discharge[t] - charge[t] == float(load[t]), "balance_{}".format(t)

        # (3) SOC 递推（步末定义）
        if t == 0:
            prob += (
                soc[0] == soc_init + (eta_c * charge[0] - discharge[0] / eta_d) * dt / cap,
                "soc_dyn_0",
            )
        else:
            prob += (
                soc[t] == soc[t - 1] + (eta_c * charge[t] - discharge[t] / eta_d) * dt / cap,
                "soc_dyn_{}".format(t),
            )

        # (6) 峰值上界
        prob += peak_var >= grid[t], "peak_def_{}".format(t)

    # (5) 终端 SOC 循环日约束
    if enforce_terminal_soc:
        prob += soc[T - 1] >= soc_init, "soc_terminal"

    # ---- 目标函数 ----
    obj = pulp.lpSum(
        [float(prices[t]) * grid[t] * dt for t in range(T)]
        + [peak_var * demand_per_kw / 30.0]
        + [discharge[t] * dt * cost_throughput for t in range(T)]
    )
    prob += obj, "objective"

    return prob, vars_dict


# --------------------------------------------------------------------------
# solve
# --------------------------------------------------------------------------
def solve(
    scenario: Scenario,
    it_power_kw: np.ndarray,
    cooling_kw: Optional[np.ndarray] = None,
    reserve_margin_kw: float = 0.0,
    enforce_terminal_soc: bool = True,
) -> Schedule:
    """构建并求解 LP，返回 ``Schedule``（``status="Optimal"`` 或抛 ``InfeasibleError``）。

    若 ``cooling_kw is None``，调用 ``src.workload.generate_cooling`` 补全。
    Schedule 的 ``grid_import_kw`` 由 ``load + charge − discharge`` 恒等式重算，
    保证功率平衡严格成立（不受 CBC 素性容差 ~1e-5 影响）。

    求解墙钟秒数写入模块级遥测 ``LAST_SOLVE_SECONDS[scenario.name]``（进程本地、
    非 LP 组成部分），由 ``compute_kpis`` 读取并填入 ``KPIs.solver_seconds``。
    """
    if cooling_kw is None:
        import src.workload as _wl
        cooling_kw = _wl.generate_cooling(it_power_kw, scenario)

    prices = scenario.price_series()
    prob, vars_dict = build_model(
        scenario, it_power_kw, cooling_kw, prices,
        reserve_margin_kw=reserve_margin_kw,
        enforce_terminal_soc=enforce_terminal_soc,
    )

    t0 = time.time()
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    elapsed = time.time() - t0
    LAST_SOLVE_SECONDS[scenario.name] = elapsed

    status_str = pulp.LpStatus[prob.status]
    if status_str != "Optimal":
        raise InfeasibleError(
            _diagnose_infeasibility(scenario, it_power_kw, cooling_kw, reserve_margin_kw)
        )

    charge_arr = np.array([vars_dict["charge"][t].value() or 0.0 for t in range(N_STEPS)], dtype=float)
    discharge_arr = np.array([vars_dict["discharge"][t].value() or 0.0 for t in range(N_STEPS)], dtype=float)
    soc_arr = np.array([vars_dict["soc"][t].value() or 0.0 for t in range(N_STEPS)], dtype=float)

    it = np.asarray(it_power_kw, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)
    load = _total_load_kw(scenario, it, cool)
    grid_arr = load + charge_arr - discharge_arr  # 恒等重算，平衡严格成立

    obj_val = float(pulp.value(prob.objective))

    sch = Schedule(
        strategy="optimal",
        charge_kw=charge_arr,
        discharge_kw=discharge_arr,
        soc=soc_arr,
        grid_import_kw=grid_arr,
        it_power_kw=it.copy(),
        cooling_kw=cool.copy(),
        objective_value=obj_val,
        status=status_str,
    )
    return sch


def _diagnose_infeasibility(
    scenario: Scenario,
    it_power_kw: np.ndarray,
    cooling_kw: np.ndarray,
    reserve_margin_kw: float,
) -> str:
    dc = scenario.datacenter
    bat = scenario.battery
    it = np.asarray(it_power_kw, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)
    load = _total_load_kw(scenario, it, cool)
    grid_limit = float(dc.grid_connection_kw) - float(reserve_margin_kw)
    max_dis = float(bat.p_discharge_max_kw)

    required = load - max_dis
    worst_t = int(np.argmax(required))
    worst_req = float(required[worst_t])

    return (
        "场景不可行：步骤 {} ({:.2f}h) 总负荷={:.1f} kW，"
        "储能放电上限={:.1f} kW 后仍需 grid ≥ {:.1f} kW，"
        "超过并网点限额 {:.1f} kW。"
        "请增大 grid_connection_kw、减小 reserve_margin_kw，或扩充储能功率/容量。"
    ).format(worst_t, worst_t * STEP_HOURS, float(load[worst_t]), max_dis, worst_req, grid_limit)


# --------------------------------------------------------------------------
# compute_kpis
# --------------------------------------------------------------------------
def compute_kpis(
    schedule: Schedule,
    scenario: Scenario,
    price_series_arr: Optional[np.ndarray] = None,
) -> KPIs:
    """从同一 ``Schedule`` 计算全部 KPI；数值口径与 LP 目标严格一致。"""
    if price_series_arr is None:
        price_series_arr = scenario.price_series()

    prices = np.asarray(price_series_arr, dtype=float)
    grid = schedule.grid_import_kw
    it = schedule.it_power_kw
    cool = schedule.cooling_kw
    discharge = schedule.discharge_kw

    dc = scenario.datacenter
    bat = scenario.battery

    dt = float(STEP_HOURS)

    # 电量电费
    electricity_cost = float(np.sum(prices * grid * dt))

    # 需量电费
    peak_kw_val = float(np.max(grid))
    demand_cost = float(dc.demand_charge_per_kw) / 30.0 * peak_kw_val

    # 老化成本（放电吞吐）
    cost_tp = throughput_cost_per_kwh(bat)
    degradation_cost = float(np.sum(discharge * dt) * cost_tp)

    total_cost = electricity_cost + demand_cost + degradation_cost

    # 谷值 / 峰谷差
    valley_grid_kw = float(np.min(grid))
    peak_valley_spread_kw = peak_kw_val - valley_grid_kw

    # 负荷率
    load_factor = float(np.mean(grid) / (peak_kw_val + 1e-12))

    # 基线（无储能）峰值：max(it + cool + ups_loss)
    base_load = _total_load_kw(scenario, it, cool)
    baseline_peak = float(np.max(base_load))
    peak_shaved_ratio = 1.0 - peak_kw_val / (baseline_peak + 1e-12)

    # 套利估算：放电吞吐 × (峰均价 − 谷均价)
    avg_price = float(np.mean(prices))
    valley_price = float(np.min(prices))
    throughput_kwh = float(np.sum(discharge * dt))
    arbitrage_saving = throughput_kwh * (avg_price - valley_price)

    saved_energy_kwh = throughput_kwh

    # PUE
    ups_kw = float(dc.ups_loss_ratio) * (it + cool)
    facility = it + cool + ups_kw
    with np.errstate(divide="ignore", invalid="ignore"):
        pue_instant = np.where(it > 0.0, facility / it, 1.0 + float(dc.ups_loss_ratio))
    avg_pue = float(np.mean(pue_instant))
    max_pue = float(np.max(pue_instant))

    # CO2：以「储能替代电网的放电能量」计（等效于削峰所避免的网电）
    co2_saved_kg = saved_energy_kwh * GRID_CO2_FACTOR

    # 求解墙钟耗时：由 solve() 写入 LAST_SOLVE_SECONDS[scenario.name] 的进程本地遥测
    solver_seconds = float(LAST_SOLVE_SECONDS.get(scenario.name, 0.0))

    return KPIs(
        strategy=schedule.strategy,
        electricity_cost=electricity_cost,
        demand_cost=demand_cost,
        total_cost=total_cost,
        degradation_cost=degradation_cost,
        peak_grid_kw=peak_kw_val,
        valley_grid_kw=valley_grid_kw,
        peak_valley_spread_kw=peak_valley_spread_kw,
        load_factor=load_factor,
        peak_shaved_ratio=peak_shaved_ratio,
        arbitrage_saving=arbitrage_saving,
        saved_energy_kwh=saved_energy_kwh,
        avg_pue=avg_pue,
        max_pue=max_pue,
        co2_saved_kg=co2_saved_kg,
        solver_seconds=solver_seconds,
    )