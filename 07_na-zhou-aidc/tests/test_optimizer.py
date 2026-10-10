"""src/optimizer.py 单元测试 —— 削峰填谷 LP 的物理可行性、经济学与不可行诊断。

口径：
- 功率平衡: grid + discharge == it + cool + charge + ups_loss
- ups_loss = ups_loss_ratio * (it + cool)
- 基线（无储能）: grid_base = it + cool + ups_loss
- 老化只计放电吞吐；SOC 步末定义，simulate_soc 闭环校验用 net = charge − discharge
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.battery import simulate_soc  # noqa: E402
from src.config import (  # noqa: E402
    N_STEPS,
    STEP_HOURS,
    Scenario,
    default_battery,
    default_scenarios,
    scenario_by_name,
)
from src.optimizer import (  # noqa: E402
    GRID_CO2_FACTOR,
    InfeasibleError,
    build_model,
    compute_kpis,
    solve,
)
from src.workload import generate_cooling, generate_it_power  # noqa: E402

TOL: float = 1e-6


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _baseline_grid(sc: Scenario, it: np.ndarray, cool: np.ndarray) -> np.ndarray:
    ups = sc.datacenter.ups_loss_ratio * (it + cool)
    return it + cool + ups


def _energy_cost(grid_kw: np.ndarray, prices: np.ndarray) -> float:
    return float(np.sum(prices * grid_kw * STEP_HOURS))


def _demand_cost(peak_kw: float, sc: Scenario) -> float:
    return sc.datacenter.demand_charge_per_kw / 30.0 * peak_kw


def _make_transient():
    sc = scenario_by_name("transient_spike")
    it = generate_it_power(sc)
    cool = generate_cooling(it, sc)
    sched = solve(sc, it, cool)
    kpis = compute_kpis(sched, sc)
    return sc, it, cool, sched, kpis


@pytest.fixture(scope="module")
def transient_result():
    return _make_transient()


# =========================================================================
# 核心求解
# =========================================================================
class TestSolveTransient:
    def test_status_optimal(self, transient_result):
        assert transient_result[3].status == "Optimal"

    def test_shapes_and_finite(self, transient_result):
        _, _, _, sched, _ = transient_result
        for arr in (sched.charge_kw, sched.discharge_kw, sched.soc,
                    sched.grid_import_kw, sched.it_power_kw, sched.cooling_kw):
            assert arr.shape == (N_STEPS,)
            assert np.all(np.isfinite(arr))

    def test_power_balance_every_step(self, transient_result):
        """grid + discharge == it + cool + charge + ups_loss，误差 < 1e-6。"""
        sc, it, cool, sched, _ = transient_result
        ups = sc.datacenter.ups_loss_ratio * (it + cool)
        lhs = sched.grid_import_kw + sched.discharge_kw
        rhs = it + cool + sched.charge_kw + ups
        assert float(np.max(np.abs(lhs - rhs))) < TOL

    def test_soc_within_bounds(self, transient_result):
        sc, _, _, sched, _ = transient_result
        bat = sc.battery
        assert float(np.min(sched.soc)) >= bat.soc_min - TOL
        assert float(np.max(sched.soc)) <= bat.soc_max + TOL

    def test_terminal_soc_cyclic(self, transient_result):
        sc, _, _, sched, _ = transient_result
        assert float(sched.soc[-1]) >= sc.battery.soc_init - 1e-9

    def test_soc_recursion_closed_loop(self, transient_result):
        """LP 的 soc 轨迹与 battery.simulate_soc 闭环一致（net = charge − discharge）。"""
        sc, _, _, sched, _ = transient_result
        net = sched.charge_kw - sched.discharge_kw
        sim = simulate_soc(net, sc.battery)
        assert float(np.max(np.abs(sim - sched.soc))) < 1e-6

    def test_grid_respects_connection_limit(self, transient_result):
        """并网硬约束：允许 CBC 求解容差量级 (~1e-4) 的边界数值误差。"""
        sc, _, _, sched, _ = transient_result
        assert float(np.max(sched.grid_import_kw)) <= sc.datacenter.grid_connection_kw + 1e-3
        assert float(np.min(sched.grid_import_kw)) >= -1e-3

    def test_power_limits(self, transient_result):
        sc, _, _, sched, _ = transient_result
        bat = sc.battery
        assert float(np.max(sched.charge_kw)) <= bat.p_charge_max_kw + TOL
        assert float(np.max(sched.discharge_kw)) <= bat.p_discharge_max_kw + TOL
        assert float(np.min(sched.charge_kw)) >= -TOL
        assert float(np.min(sched.discharge_kw)) >= -TOL

    def test_input_validation(self):
        sc = scenario_by_name("baseline_day")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        with pytest.raises(ValueError):
            build_model(sc, it[:-1], cool, sc.price_series())
        with pytest.raises(ValueError):
            build_model(sc, it, cool[:-1], sc.price_series())
        with pytest.raises(ValueError):
            build_model(sc, it, cool, sc.price_series()[:-1])


# =========================================================================
# 纯 LP 合理性：互补条件数值验证
# =========================================================================
class TestPureLPComplementarity:
    def test_no_simultaneous_charge_discharge(self, transient_result):
        """效率损失 + 吞吐成本使充放同开严格劣；LP 顶点解无同时充放。"""
        _, _, _, sched, _ = transient_result
        overlap = np.minimum(sched.charge_kw, sched.discharge_kw)
        assert float(np.max(overlap)) < TOL

    def test_all_variables_continuous(self):
        """LP 不引入二进制/整数变量（纯 LP）：cat 全为 'Continuous'。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        prob, vars_dict = build_model(sc, it, cool, sc.price_series())
        assert {v.cat for v in prob.variables()} == {"Continuous"}
        for name in ("charge", "discharge", "soc", "grid_import"):
            for t in range(N_STEPS):
                assert vars_dict[name][t].cat == "Continuous"
        assert vars_dict["peak_kw"].cat == "Continuous"


# =========================================================================
# 削峰与成本对比
# =========================================================================
class TestPeakShaving:
    def test_peak_reduced_vs_baseline(self, transient_result):
        sc, it, cool, sched, kpis = transient_result
        baseline_peak = float(np.max(_baseline_grid(sc, it, cool)))
        optimized_peak = float(np.max(sched.grid_import_kw))
        assert optimized_peak < baseline_peak
        assert kpis.peak_shaved_ratio > 0.0

    def test_total_cost_strictly_lower_than_baseline(self, transient_result):
        """优化综合成本 < 无储能基线（电量+需量，基线无老化成本）。"""
        sc, it, cool, sched, kpis = transient_result
        base_grid = _baseline_grid(sc, it, cool)
        prices = sc.price_series()
        baseline_total = _energy_cost(base_grid, prices) + _demand_cost(
            float(np.max(base_grid)), sc
        )
        assert kpis.total_cost < baseline_total

    def test_kpi_internals_consistent(self, transient_result):
        sc, it, cool, sched, kpis = transient_result
        prices = sc.price_series()
        bat = sc.battery
        assert abs(kpis.electricity_cost - _energy_cost(sched.grid_import_kw, prices)) < 1e-6
        assert abs(kpis.demand_cost - _demand_cost(float(np.max(sched.grid_import_kw)), sc)) < 1e-6
        assert abs(kpis.total_cost - (kpis.electricity_cost + kpis.demand_cost + kpis.degradation_cost)) < 1e-6
        tp_cost = bat.capex_per_kwh / bat.cycle_life + bat.om_cost_per_kwh
        assert abs(kpis.degradation_cost - float(np.sum(sched.discharge_kw * STEP_HOURS)) * tp_cost) < 1e-6
        base_peak = float(np.max(_baseline_grid(sc, it, cool)))
        assert abs(kpis.peak_shaved_ratio - (1.0 - kpis.peak_grid_kw / base_peak)) < 1e-9
        assert kpis.avg_pue > 1.0
        assert kpis.max_pue >= kpis.avg_pue
        assert abs(kpis.co2_saved_kg - kpis.saved_energy_kwh * GRID_CO2_FACTOR) < 1e-6
        assert kpis.co2_saved_kg > 0.0

    def test_objective_matches_kpi_total(self, transient_result):
        """LP 目标值 == KPI 三项成本之和（同一模块口径）。"""
        _, _, _, sched, kpis = transient_result
        assert abs(sched.objective_value - kpis.total_cost) < 1e-3

    def test_valley_filling_behavior(self, transient_result):
        """低价谷段充电显著多于峰段——「填谷」效果。"""
        sc, _, _, sched, _ = transient_result
        prices = sc.price_series()
        valley = prices <= sc.tariff.valley_price
        peak = prices >= sc.tariff.peak_price
        assert float(np.sum(sched.charge_kw[valley])) > float(np.sum(sched.charge_kw[peak]))


# =========================================================================
# 不可行诊断
# =========================================================================
class TestInfeasibility:
    def test_grid_below_peak_raises_infeasible(self):
        """并网限额压到峰值负荷以下 → InfeasibleError。"""
        sc = scenario_by_name("transient_spike")
        sc.datacenter.grid_connection_kw = 500.0
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        with pytest.raises(InfeasibleError):
            solve(sc, it, cool)

    def test_infeasible_message_has_step_and_kw(self):
        sc = scenario_by_name("transient_spike")
        sc.datacenter.grid_connection_kw = 500.0
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        with pytest.raises(InfeasibleError) as excinfo:
            solve(sc, it, cool)
        msg = str(excinfo.value)
        assert "步骤" in msg
        assert "kW" in msg

    def test_reserve_margin_blocks_feasible_case(self):
        """reserve_margin（N-1 备用）逼近能力极限时不可行；margin=0 可行。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        sched = solve(sc, it, cool, reserve_margin_kw=0.0)
        assert sched.status == "Optimal"
        # 只留 200 kW 有效限额 → 必然不可行
        with pytest.raises(InfeasibleError):
            solve(sc, it, cool, reserve_margin_kw=sc.datacenter.grid_connection_kw - 200.0)

    def test_nonpositive_effective_limit_raises_valueerror(self):
        sc = scenario_by_name("baseline_day")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        with pytest.raises(ValueError):
            solve(sc, it, cool, reserve_margin_kw=sc.datacenter.grid_connection_kw + 1.0)


# =========================================================================
# 其他情景、cooling 缺省与终端 SOC 开关
# =========================================================================
class TestScenarios:
    @pytest.mark.parametrize("name", ["baseline_day", "transient_spike"])
    def test_feasible_scenarios_optimal(self, name):
        sc = scenario_by_name(name)
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        sched = solve(sc, it, cool)
        assert sched.status == "Optimal"
        ups = sc.datacenter.ups_loss_ratio * (it + cool)
        assert float(np.max(np.abs(
            sched.grid_import_kw + sched.discharge_kw - it - cool - sched.charge_kw - ups
        ))) < TOL
        assert float(np.max(np.minimum(sched.charge_kw, sched.discharge_kw))) < TOL

    def test_extreme_peak_needs_augmented_battery(self):
        """extreme_peak 默认 500 kW 储能不可行；扩至 5000 kW/20000 kWh 后可解。"""
        sc = scenario_by_name("extreme_peak")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        sc.battery = default_battery()
        with pytest.raises(InfeasibleError):
            solve(sc, it, cool)
        sc.battery = scenario_by_name("extreme_peak").battery
        sched = solve(sc, it, cool, enforce_terminal_soc=False)
        assert sched.status == "Optimal"

    def test_cooling_none_falls_back_to_workload(self):
        sc = scenario_by_name("baseline_day")
        it = generate_it_power(sc)
        sched = solve(sc, it)
        assert sched.status == "Optimal"
        expected = generate_cooling(it, sc)
        assert float(np.max(np.abs(sched.cooling_kw - expected))) < 1e-9

    def test_enforce_terminal_soc_false_relaxes(self):
        """关闭终端 SOC 约束后仍可解，且目标值不高于开启时（可行集扩大）。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        tight = solve(sc, it, cool, enforce_terminal_soc=True)
        loose = solve(sc, it, cool, enforce_terminal_soc=False)
        assert loose.status == "Optimal"
        assert loose.objective_value <= tight.objective_value + 1e-3

    def test_deterministic_same_seed(self):
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        s1 = solve(sc, it, cool)
        s2 = solve(sc, it, cool)
        assert abs(s1.objective_value - s2.objective_value) < 1e-3
        assert float(np.max(np.abs(s1.soc - s2.soc))) < 1e-6

    def test_default_scenarios_all_constructible(self):
        for sc in default_scenarios():
            it = generate_it_power(sc)
            assert it.shape == (N_STEPS,)
            assert sc.price_series().shape == (N_STEPS,)

    def test_reserve_margin_small_stays_feasible(self):
        """小裕度仍可解，并网点取电不超过扣除裕度后的有效限额。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        reserve = 100.0
        sched = solve(sc, it, cool, reserve_margin_kw=reserve)
        assert sched.status == "Optimal"
        effective_limit = sc.datacenter.grid_connection_kw - reserve
        assert float(np.max(sched.grid_import_kw)) <= effective_limit + 1e-3

    def test_reserve_margin_500_diagnosed_infeasible(self):
        """裕度过大把有效限额压到 7500 kW，低于储能补不上的需求 → InfeasibleError 点名步骤与限额。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        reserve = 500.0
        with pytest.raises(InfeasibleError) as exc:
            solve(sc, it, cool, reserve_margin_kw=reserve)
        msg = str(exc.value)
        effective_limit = sc.datacenter.grid_connection_kw - reserve
        assert "步骤" in msg
        assert "{:.1f}".format(effective_limit) in msg

    def test_solver_seconds_populated(self):
        """solve() 写入 LAST_SOLVE_SECONDS 遥测，compute_kpis 读出 solver_seconds > 0。"""
        sc = scenario_by_name("transient_spike")
        it = generate_it_power(sc)
        sched = solve(sc, it)
        kpis = compute_kpis(sched, sc)
        assert kpis.solver_seconds > 0.0