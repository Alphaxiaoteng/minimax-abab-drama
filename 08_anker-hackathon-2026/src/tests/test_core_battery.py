"""Tests for core.battery: step() 语义、SOC 夹逼、温度降额、退化成本公式。"""
from __future__ import annotations

import math

import pytest

from core.battery import BatteryConfig, BatteryState, BatteryModel


@pytest.fixture
def cfg():
    return BatteryConfig(
        capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5,
        round_trip_eff=0.90, soc_min=0.05, soc_max=1.0, soc_start=0.50,
        cycle_life=6000, pack_cost_cny=12000.0, reserve_soc=0.10,
    )


@pytest.fixture
def model(cfg):
    return BatteryModel(cfg)


class TestStep:
    def test_charge_increases_soc(self, model):
        state = BatteryState(soc=0.5)
        new, deg = model.step(state, power_kw=2.0, hours=1.0)
        sqrt_rte = math.sqrt(0.90)
        expected_soc = 0.5 + 2.0 * sqrt_rte / 5.0
        assert new.soc == pytest.approx(expected_soc, abs=1e-6)
        assert new.soc > state.soc
        assert deg >= 0

    def test_discharge_decreases_soc(self, model):
        state = BatteryState(soc=0.8)
        new, deg = model.step(state, power_kw=-2.0, hours=1.0)
        sqrt_rte = math.sqrt(0.90)
        expected_soc = 0.8 - 2.0 / sqrt_rte / 5.0
        assert new.soc == pytest.approx(expected_soc, abs=1e-6)
        assert new.soc < state.soc

    def test_zero_power_no_change(self, model):
        state = BatteryState(soc=0.5)
        new, deg = model.step(state, power_kw=0.0, hours=1.0)
        assert new.soc == pytest.approx(0.5)
        assert deg == 0.0

    def test_does_not_mutate_input(self, model):
        state = BatteryState(soc=0.5, cycles=1.0)
        model.step(state, power_kw=2.0, hours=1.0)
        assert state.soc == 0.5
        assert state.cycles == 1.0

    def test_clamps_at_soc_max(self, model):
        state = BatteryState(soc=0.99)
        new, _ = model.step(state, power_kw=2.5, hours=1.0)
        assert new.soc <= 1.0 + 1e-9

    def test_clamps_at_soc_min(self, model):
        state = BatteryState(soc=0.06)
        new, _ = model.step(state, power_kw=-2.5, hours=1.0)
        assert new.soc >= 0.05 - 1e-9

    def test_clamps_power_at_soc_max(self, model):
        state = BatteryState(soc=0.99)
        new, _ = model.step(state, power_kw=10.0, hours=1.0)
        assert new.soc <= 1.0 + 1e-9

    def test_clamps_power_at_soc_min(self, model):
        state = BatteryState(soc=0.06)
        new, _ = model.step(state, power_kw=-10.0, hours=1.0)
        assert new.soc >= 0.05 - 1e-9

    def test_accumulates_cycles(self, model):
        state = BatteryState(soc=0.5, cycles=0.0)
        new, _ = model.step(state, power_kw=2.5, hours=1.0)
        expected_cycles = 2.5 * 1.0 / (2.0 * 5.0)
        assert new.cycles == pytest.approx(expected_cycles, abs=1e-6)


class TestTemperatureDerating:
    def test_no_derate_at_25(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 2.5, temp_c=25.0)
        assert p == pytest.approx(2.5)

    def test_derate_at_50(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 2.5, temp_c=50.0)
        derate = 1.0 - 0.5 * (50.0 - 45.0) / 15.0
        expected = 2.5 * derate
        assert p == pytest.approx(expected, abs=0.01)

    def test_derate_at_60_gives_half(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 2.5, temp_c=60.0)
        assert p == pytest.approx(2.5 * 0.5, abs=0.01)

    def test_derate_clamped_to_half_above_60(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 2.5, temp_c=100.0)
        assert p == pytest.approx(2.5 * 0.5, abs=0.01)


class TestDegradationCost:
    def test_formula(self, model):
        cost = model.degradation_cost(1.0)
        expected = 1.0 * 12000.0 / (6000 * 2 * 5.0)
        assert cost == pytest.approx(expected, abs=1e-9)

    def test_proportional_to_throughput(self, model):
        c1 = model.degradation_cost(1.0)
        c3 = model.degradation_cost(3.0)
        assert c3 == pytest.approx(3 * c1, abs=1e-9)


class TestFeasiblePower:
    def test_clamps_to_max_charge(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 5.0)
        assert p == pytest.approx(2.5)

    def test_clamps_to_max_discharge(self, model):
        p = model.feasible_power(BatteryState(soc=0.9), -5.0)
        assert p == pytest.approx(-2.5)

    def test_returns_zero_for_zero(self, model):
        p = model.feasible_power(BatteryState(soc=0.5), 0.0)
        assert p == 0.0