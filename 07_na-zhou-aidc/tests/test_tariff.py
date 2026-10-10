"""tests/test_tariff.py —— 分时电价与电费计算单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.config import (  # noqa: E402
    N_STEPS,
    STEP_HOURS,
    BatteryParams,
    default_battery,
    default_tariff,
    price_for_hour,
)
from src.tariff import (  # noqa: E402
    arbitrage_headroom,
    demand_charge,
    energy_cost,
    peak_valley_spread,
    price_series,
    total_tou_cost,
    tou_breakdown,
)


# --------------------------------------------------------------------------
# price_series
# --------------------------------------------------------------------------
def test_price_series_length_96():
    prices = price_series(default_tariff())
    assert prices.shape == (N_STEPS,)
    assert np.isfinite(prices).all()


def test_price_series_matches_tariff_price_at():
    tariff = default_tariff()
    prices = price_series(tariff)
    assert np.allclose(prices, [tariff.price_at(i) for i in range(N_STEPS)])


def test_price_levels_monotone_ordered():
    """sharp > peak > flat > valley（元/kWh）。"""
    tariff = default_tariff()
    valley = price_for_hour(tariff, 3.0)
    flat = price_for_hour(tariff, 7.5)
    peak = price_for_hour(tariff, 9.0)
    sharp = price_for_hour(tariff, 10.5)
    assert sharp > peak > flat > valley
    prices = price_series(tariff)
    assert prices.min() == pytest.approx(valley)
    assert prices.max() == pytest.approx(sharp)


# --------------------------------------------------------------------------
# energy_cost
# --------------------------------------------------------------------------
def test_energy_cost_flat_load():
    """平稳 1000 kW 负荷：电费 == 1000 * step_hours * mean(price)。"""
    prices = price_series(default_tariff())
    power = np.full(N_STEPS, 1000.0)
    expected = 1000.0 * STEP_HOURS * float(prices.sum())
    assert energy_cost(power, prices, STEP_HOURS) == pytest.approx(expected, abs=1e-6)


def test_energy_cost_manual_dot_product():
    power = np.array([100.0, 200.0, 300.0])
    prices = np.array([0.3, 0.6, 1.0])
    expected = (100 * 0.3 + 200 * 0.6 + 300 * 1.0) * STEP_HOURS
    assert energy_cost(power, prices, STEP_HOURS) == pytest.approx(expected, abs=1e-9)


def test_energy_cost_rejects_mismatch_and_negative():
    prices = price_series(default_tariff())
    with pytest.raises(ValueError):
        energy_cost(np.ones(N_STEPS - 1), prices)
    with pytest.raises(ValueError):
        energy_cost(-np.ones(N_STEPS), prices)


# --------------------------------------------------------------------------
# demand_charge
# --------------------------------------------------------------------------
def test_demand_charge_proration_days_30():
    """days=30 → 恰为整月单价 × 峰值。"""
    peak = 5000.0
    per_kw = 42.0
    assert demand_charge(peak, per_kw, days=30.0) == pytest.approx(peak * per_kw)


def test_demand_charge_linear_in_days():
    peak = 5000.0
    per_kw = 42.0
    month = demand_charge(peak, per_kw, days=30.0)
    assert demand_charge(peak, per_kw, days=15.0) == pytest.approx(0.5 * month)
    assert demand_charge(peak, per_kw, days=1.0) == pytest.approx(month / 30.0)


def test_demand_charge_validation():
    with pytest.raises(ValueError):
        demand_charge(-1.0, 42.0)
    with pytest.raises(ValueError):
        demand_charge(100.0, 42.0, days=0.0)
    with pytest.raises(ValueError):
        demand_charge(float("nan"), 42.0)


# --------------------------------------------------------------------------
# total_tou_cost
# --------------------------------------------------------------------------
def test_total_tou_cost_combines_energy_and_demand():
    tariff = default_tariff()
    prices = price_series(tariff)
    power = np.full(N_STEPS, 1000.0)
    peak = float(power.max())
    per_kw = 42.0
    total = total_tou_cost(power, prices, peak, per_kw, days=1.0)
    assert total == pytest.approx(
        energy_cost(power, prices) + demand_charge(peak, per_kw, days=1.0),
        abs=1e-9,
    )


# --------------------------------------------------------------------------
# tou_breakdown
# --------------------------------------------------------------------------
def test_tou_breakdown_sums_to_energy_cost():
    prices = price_series(default_tariff())
    rng = np.random.RandomState(7)
    power = rng.uniform(500.0, 2000.0, size=N_STEPS)
    bd = tou_breakdown(power, prices, STEP_HOURS)
    levels = ("valley", "flat", "peak", "sharp")
    assert sum(bd["{}_cost".format(lv)] for lv in levels) == pytest.approx(
        energy_cost(power, prices), abs=1e-6
    )
    assert bd["total_cost"] == pytest.approx(energy_cost(power, prices), abs=1e-6)
    assert sum(bd["{}_energy_kwh".format(lv)] for lv in levels) == pytest.approx(
        float(power.sum() * STEP_HOURS), abs=1e-6
    )


def test_tou_breakdown_covers_all_steps_and_ordering():
    """谷段（0-7 与 23-24 时）步数 = 32；单价随档位单调。"""
    tariff = default_tariff()
    prices = price_series(tariff)
    power = np.ones(N_STEPS)
    bd = tou_breakdown(power, prices, STEP_HOURS)
    valley_steps = bd["valley_energy_kwh"] / STEP_HOURS
    assert valley_steps == pytest.approx(32.0)
    unit = {
        lv: bd["{}_cost".format(lv)] / bd["{}_energy_kwh".format(lv)]
        for lv in ("valley", "flat", "peak", "sharp")
    }
    assert unit["sharp"] > unit["peak"] > unit["flat"] > unit["valley"]


# --------------------------------------------------------------------------
# peak_valley_spread / arbitrage_headroom
# --------------------------------------------------------------------------
def test_peak_valley_spread():
    prices = price_series(default_tariff())
    assert peak_valley_spread(prices) == pytest.approx(1.28 - 0.30)


def test_arbitrage_headroom_formula():
    """headroom == min(usable_kwh, p_charge * valley_hours) * spread。"""
    tariff = default_tariff()
    prices = price_series(tariff)
    battery = default_battery()
    valley_hours = 8.0  # 0:00-7:00 + 23:00:00-24:00
    expected = min(
        battery.usable_kwh, battery.p_charge_max_kw * valley_hours
    ) * peak_valley_spread(prices)
    assert arbitrage_headroom(prices, battery) == pytest.approx(expected)


def test_arbitrage_headroom_charging_power_limited_branch():
    """充电功率受限（小功率电池）时取 valley_kwh 分支。"""
    prices = price_series(default_tariff())
    battery = BatteryParams(
        capacity_kwh=10000.0,
        p_charge_max_kw=100.0,
        soc_min=0.0,
        soc_max=1.0,
    )
    valley_kwh = 100.0 * 8.0
    assert valley_kwh < battery.usable_kwh
    assert arbitrage_headroom(prices, battery) == pytest.approx(
        valley_kwh * peak_valley_spread(prices)
    )


if __name__ == "__main__":
    battery = default_battery()
    print("arbitrage_headroom (default battery) =",
          arbitrage_headroom(price_series(default_tariff()), battery))