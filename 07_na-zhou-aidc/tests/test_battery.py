"""电池模型单元测试 —— SOC 守恒、越界校验、老化成本线性。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# 将仓库根目录加入 sys.path，使 ``src`` 包可被导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.battery import (  # noqa: E402
    degradation_cost,
    max_absorbable_kw,
    max_deliverable_kw,
    simulate_soc,
    soc_bounds,
    throughput_cost_per_kwh,
    validate_params,
)
from src.config import BatteryParams, default_battery, STEP_HOURS  # noqa: E402


# =========================================================================
# validate_params
# =========================================================================
class TestValidateParams:
    """非法参数校验。"""

    def test_default_battery_passes(self) -> None:
        validate_params(default_battery())

    def test_soc_min_gte_soc_max_raises(self) -> None:
        p = default_battery()
        p.soc_min = 0.9
        p.soc_max = 0.5
        with pytest.raises(ValueError, match="soc_min"):
            validate_params(p)

    def test_soc_min_eq_soc_max_raises(self) -> None:
        p = default_battery()
        p.soc_min = 0.5
        p.soc_max = 0.5
        with pytest.raises(ValueError, match="soc_min"):
            validate_params(p)

    def test_eta_zero_raises(self) -> None:
        p = default_battery()
        p.eta_charge = 0.0
        with pytest.raises(ValueError, match="eta_charge"):
            validate_params(p)

    def test_eta_gt_one_raises(self) -> None:
        p = default_battery()
        p.eta_discharge = 1.01
        with pytest.raises(ValueError, match="eta_discharge"):
            validate_params(p)

    def test_non_positive_capacity_raises(self) -> None:
        p = default_battery()
        p.capacity_kwh = 0.0
        with pytest.raises(ValueError, match="capacity_kwh"):
            validate_params(p)

    def test_negative_power_raises(self) -> None:
        p = default_battery()
        p.p_charge_max_kw = -10.0
        with pytest.raises(ValueError, match="p_charge_max_kw"):
            validate_params(p)

    def test_soc_init_outside_bounds_raises(self) -> None:
        p = default_battery()
        p.soc_init = 0.95  # 超出 soc_max=0.90
        with pytest.raises(ValueError, match="soc_init"):
            validate_params(p)


# =========================================================================
# soc_bounds
# =========================================================================
class TestSocBounds:
    def test_returns_tuple(self) -> None:
        p = default_battery()
        lo, hi = soc_bounds(p)
        assert lo == p.soc_min
        assert hi == p.soc_max


# =========================================================================
# simulate_soc
# =========================================================================
class TestSimulateSoc:
    """SOC 递推与越界校验。"""

    def test_round_trip_efficiency(self) -> None:
        """充 100 kWh 再放 100 kWh，SOC 净减少等于往返效率损失。"""
        p = default_battery()
        # 充电功率 400 kW, 0.25h → 400*0.25=100 kWh 入端口
        # 放电功率 400 kW, 0.25h → 400*0.25=100 kWh 出端口
        power = np.array([400.0, -400.0])
        soc = simulate_soc(power, p)
        # 充电后: soc_init + eta_charge * 400 * 0.25 / capacity
        expected_after_charge = p.soc_init + p.eta_charge * 400.0 * 0.25 / p.capacity_kwh
        assert soc[0] == pytest.approx(expected_after_charge)
        # 放电后: soc[0] - (400 * 0.25 / eta_discharge) / capacity
        delta_discharge_kwh_internal = 400.0 * 0.25 / p.eta_discharge
        expected_final = soc[0] - delta_discharge_kwh_internal / p.capacity_kwh
        assert soc[1] == pytest.approx(expected_final)
        # 净 SOC 变化: 充电进入 eta_charge*100, 放电取出 100/eta_discharge
        # 往返效率损失 = 100*(1/eta_d - eta_c) / capacity
        net_loss_kwh = 100.0 / p.eta_discharge - p.eta_charge * 100.0
        assert soc[1] == pytest.approx(p.soc_init - net_loss_kwh / p.capacity_kwh)

    def test_zero_power_constant_soc(self) -> None:
        p = default_battery()
        power = np.zeros(10)
        soc = simulate_soc(power, p)
        np.testing.assert_allclose(soc, p.soc_init)

    def test_violates_soc_min_raises(self) -> None:
        """大幅放电使 SOC 跌破 soc_min，应抛 ValueError。"""
        p = default_battery()
        # 从 soc_init=0.5 开始，放 0.5*2000 = 1000 kWh，soc_min=0.1 只允许 800 kWh
        # 以 500 kW 放电，需 500/eta_d * 0.25 = ~131.6 kWh/步（内部）
        # 8 步 = ~1053 kWh，足以越界
        power = np.full(10, -500.0)
        with pytest.raises(ValueError, match="SOC 轨迹越界"):
            simulate_soc(power, p)

    def test_violates_soc_max_raises(self) -> None:
        """大幅充电使 SOC 超过 soc_max，应抛 ValueError。"""
        p = default_battery()
        # soc_max=0.9，soc_init=0.5，可用 0.4*2000=800 kWh
        # 500 kW * eta_c * 0.25 = 118.75 kWh/步，7步=831 kWh > 800 → 越界
        power = np.full(10, 500.0)
        with pytest.raises(ValueError, match="SOC 轨迹越界"):
            simulate_soc(power, p)

    def test_output_length_matches_input(self) -> None:
        p = default_battery()
        power = np.array([0.0] * 24)
        soc = simulate_soc(power, p)
        assert len(soc) == 24

    def test_output_is_end_of_step(self) -> None:
        """soc[0] 不等于 soc_init，而是第一步执行后的值。"""
        p = default_battery()
        power = np.array([100.0])  # 100 kW 充电一步
        soc = simulate_soc(power, p)
        assert soc[0] != p.soc_init
        assert soc[0] > p.soc_init  # 充电使 SOC 上升


# =========================================================================
# max_deliverable_kw / max_absorbable_kw
# =========================================================================
class TestPowerCapability:
    def test_max_deliverable_at_lower_bound_is_zero(self) -> None:
        p = default_battery()
        assert max_deliverable_kw(p.soc_min, p, 1.0) == 0.0

    def test_max_deliverable_respects_power_limit(self) -> None:
        p = default_battery()
        # soc=0.9 可用能量 = (0.9-0.1)*2000=1600 kWh → 1h 可放 1600*0.95=1520 kW
        # 但受 p_discharge_max_kw=500 限制
        result = max_deliverable_kw(0.9, p, 1.0)
        assert result == p.p_discharge_max_kw

    def test_max_deliverable_energy_limited(self) -> None:
        p = default_battery()
        # 短时间: soc=0.2, hours=0.25 → 可用 (0.2-0.1)*2000=200 kWh
        # P = 200 * 0.95 / 0.25 = 760 kW → 但受 p_discharge_max_kw=500
        result = max_deliverable_kw(0.2, p, 0.25)
        assert result == p.p_discharge_max_kw

    def test_max_deliverable_long_duration_energy_limited(self) -> None:
        p = default_battery()
        # soc=0.2, hours=10 → 可用 200*0.95/10 = 19 kW
        result = max_deliverable_kw(0.2, p, 10.0)
        assert result == pytest.approx((0.2 - p.soc_min) * p.capacity_kwh * p.eta_discharge / 10.0)
        assert result < p.p_discharge_max_kw

    def test_max_absorbable_at_upper_bound_is_zero(self) -> None:
        p = default_battery()
        assert max_absorbable_kw(p.soc_max, p, 1.0) == 0.0

    def test_max_absorbable_respects_power_limit(self) -> None:
        p = default_battery()
        result = max_absorbable_kw(0.1, p, 1.0)
        # 空间 = (0.9-0.1)*2000 = 1600, P = 1600/(0.95*1) = 1684 kW → 限 500
        assert result == p.p_charge_max_kw

    def test_max_absorbable_energy_limited(self) -> None:
        p = default_battery()
        # soc=0.8, hours=10 → 空间 = (0.9-0.8)*2000 = 200
        # P = 200/(0.95*10) ≈ 21.05 kW < 500
        result = max_absorbable_kw(0.8, p, 10.0)
        expected = (0.9 - 0.8) * p.capacity_kwh / (p.eta_charge * 10.0)
        assert result == pytest.approx(expected)

    def test_max_deliverable_zero_hours_raises(self) -> None:
        p = default_battery()
        with pytest.raises(ValueError, match="hours"):
            max_deliverable_kw(0.5, p, 0.0)

    def test_max_absorbable_negative_hours_raises(self) -> None:
        p = default_battery()
        with pytest.raises(ValueError, match="hours"):
            max_absorbable_kw(0.5, p, -1.0)

    def test_deliverable_feeds_simulate_soc_consistency(self) -> None:
        """max_deliverable_kw 的功率用满 hours 后恰到达 soc_min（模拟从 soc_init 起步）。"""
        p = default_battery()
        hours = 2.0  # 使能量限制生效（380 kW < 500 kW 上限）
        assert max_deliverable_kw(p.soc_init, p, hours) < p.p_discharge_max_kw
        # simulate_soc 从 params.soc_init 起步
        deliverable = max_deliverable_kw(p.soc_init, p, hours)
        n_steps = int(hours / STEP_HOURS)
        power = np.full(n_steps, -deliverable)
        soc = simulate_soc(power, p)
        assert soc[-1] == pytest.approx(p.soc_min, abs=1e-9)


# =========================================================================
# degradation_cost / throughput_cost_per_kwh
# =========================================================================
class TestDegradationCost:
    def test_linearity_double_throughput(self) -> None:
        p = default_battery()
        cost_100 = degradation_cost(100.0, p)
        cost_200 = degradation_cost(200.0, p)
        assert cost_200 == pytest.approx(2.0 * cost_100)

    def test_linearity_arbitrary_ratios(self) -> None:
        p = default_battery()
        for ratio in (3.0, 7.5, 0.01):
            assert degradation_cost(ratio * 50.0, p) == pytest.approx(ratio * degradation_cost(50.0, p))

    def test_zero_throughput_returns_zero(self) -> None:
        p = default_battery()
        assert degradation_cost(0.0, p) == 0.0

    def test_negative_throughput_returns_zero(self) -> None:
        p = default_battery()
        assert degradation_cost(-100.0, p) == 0.0

    def test_formula_matches_throughput_cost(self) -> None:
        """degradation_cost(1, p) == throughput_cost_per_kwh(p)"""
        p = default_battery()
        assert degradation_cost(1.0, p) == pytest.approx(throughput_cost_per_kwh(p))

    def test_explicit_value_check(self) -> None:
        p = default_battery()
        # capex_per_kwh=900, cycle_life=4000, om_cost=0.02
        # 度电成本 = 900/4000 + 0.02 = 0.225 + 0.02 = 0.245
        expected = 900.0 / 4000.0 + 0.02
        assert throughput_cost_per_kwh(p) == pytest.approx(expected)
        assert degradation_cost(1000.0, p) == pytest.approx(expected * 1000.0)

    def test_nan_throughput_raises(self) -> None:
        p = default_battery()
        with pytest.raises(ValueError, match="有限"):
            degradation_cost(float("nan"), p)

    def test_inf_throughput_raises(self) -> None:
        p = default_battery()
        with pytest.raises(ValueError, match="有限"):
            degradation_cost(float("inf"), p)