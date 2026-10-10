"""PUE 分析模块的确定性单元测试（无网络、无求解器依赖）。

口径依据（冻结物理契约）：
    ups_loss[t] = ups_loss_ratio * (it_power[t] + cooling[t])
    facility    = it + cooling + ups_loss (+ 储能往返损耗)
    PUE         = facility / it
因此「纯 IT、零制冷」时 PUE = 1 + ups_loss_ratio，而非 1/(1-ups_loss)。
"""
from __future__ import annotations

import numpy as np
import pytest

from src.config import N_STEPS, STEP_HOURS, default_datacenter
from src.pue import (
    annualized_pue,
    cooling_energy_share,
    decompose_facility_power,
    instantaneous_pue,
    pue_improvement_levers,
    pue_quantiles,
    pue_with_vs_without_storage,
)
from src.types import Schedule


def _zeros(n: int = N_STEPS) -> np.ndarray:
    return np.zeros(n, dtype=float)


def _make_schedule(
    it_kw: np.ndarray,
    cool_kw: np.ndarray,
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    grid_kw: np.ndarray,
    strategy: str,
) -> Schedule:
    soc = np.full_like(it_kw, 0.5)
    return Schedule(
        strategy=strategy,
        charge_kw=charge_kw,
        discharge_kw=discharge_kw,
        soc=soc,
        grid_import_kw=grid_kw,
        it_power_kw=it_kw,
        cooling_kw=cool_kw,
    )


# --------------------------------------------------------------------------
# 1. 瞬时 PUE
# --------------------------------------------------------------------------
def test_pure_it_zero_cooling_zero_ups_is_exactly_one():
    """instantaneous_pue(1000, 0, 0.0) == 1.0 精确成立（契约基准点）。"""
    pue = instantaneous_pue(np.array([1000.0]), np.array([0.0]), 0.0)
    assert float(pue[0]) == 1.0
    # 标量输入也应工作（内部转 ndarray）。
    assert float(instantaneous_pue(1000, 0, 0.0)) == 1.0


def test_pure_it_ups_gives_one_plus_ratio():
    """零制冷时 PUE = 1 + ups_loss_ratio（按冻结口径，非 1/(1-ups)）。"""
    ratio = 0.05
    pue = instantaneous_pue(np.array([1000.0]), np.array([0.0]), ratio)
    assert pue[0] == 1.0 + ratio


def test_pue_always_at_least_one():
    """任意正负荷组合，PUE 恒 >= 1.0。"""
    rng = np.random.default_rng(1234)
    it = rng.uniform(200.0, 9000.0, size=N_STEPS)
    cool = it * rng.uniform(0.1, 0.6, size=N_STEPS)
    pue = instantaneous_pue(it, cool, default_datacenter().ups_loss_ratio)
    assert np.all(pue >= 1.0)


def test_pue_zero_it_guarded_no_nan_inf():
    """IT=0 点被保护为 1.0，不产生 NaN/Inf。"""
    it = np.array([0.0, 0.0, 1000.0])
    cool = np.array([50.0, 0.0, 320.0])
    pue = instantaneous_pue(it, cool, 0.03)
    assert np.isfinite(pue).all()
    assert pue[0] == 1.0
    assert pue[1] == 1.0
    assert pue[2] == pytest.approx((1000.0 + 320.0) * 1.03 / 1000.0)


# --------------------------------------------------------------------------
# 2. 分位数有序
# --------------------------------------------------------------------------
def test_quantiles_are_ordered():
    rng = np.random.default_rng(7)
    it = rng.uniform(500.0, 9000.0, size=N_STEPS)
    cool = it * 0.32
    pue = instantaneous_pue(it, cool, 0.03)
    q = pue_quantiles(pue)
    assert set(q.keys()) == {"p05", "p50", "p95"}
    assert q["p05"] <= q["p50"] <= q["p95"]
    assert all(np.isfinite(list(q.values())))
    assert all(v >= 1.0 for v in q.values())


def test_quantiles_custom_probs_keys():
    q = pue_quantiles(np.linspace(1.1, 1.4, 50), probs=(0.1, 0.5, 0.9))
    assert list(q.keys()) == ["p10", "p50", "p90"]
    assert q["p10"] <= q["p50"] <= q["p90"]


# --------------------------------------------------------------------------
# 3. 年化 PUE
# --------------------------------------------------------------------------
def test_annualized_pue_in_reasonable_band():
    rng = np.random.default_rng(11)
    it = rng.uniform(3000.0, 6000.0, size=N_STEPS)
    cool = it * 0.32
    pue = instantaneous_pue(it, cool, 0.03)
    annual = annualized_pue(pue)
    assert isinstance(annual, float)
    assert 1.0 <= annual <= 2.0


def test_annualized_pue_weights_must_sum_to_one():
    pue = np.full(N_STEPS, 1.3)
    # 合法：0.3 + 0.2 + 0.5 = 1.0
    assert annualized_pue(pue, 0.3, 0.2, 0.5) > 1.0
    try:
        annualized_pue(pue, 0.5, 0.5, 0.5)
    except ValueError:
        pass
    else:
        raise AssertionError("权重和不为 1 时应抛 ValueError")


# --------------------------------------------------------------------------
# 4. 制冷能耗占比
# --------------------------------------------------------------------------
def test_cooling_energy_share_in_open_unit_interval():
    it = np.full(N_STEPS, 3000.0)
    cool = it * 0.32
    share = cooling_energy_share(it, cool, 0.03)
    assert 0.0 < share < 1.0
    expected = 0.32 / 1.32 / 1.03
    assert share == pytest.approx(expected, rel=1e-6)


def test_cooling_energy_share_no_cooling_is_zero():
    it = np.full(N_STEPS, 3000.0)
    cool = _zeros()
    assert cooling_energy_share(it, cool, 0.03) == 0.0


# --------------------------------------------------------------------------
# 5. 有/无储能对比：PUE 不改善（诚实量化）
# --------------------------------------------------------------------------
def test_storage_does_not_improve_pue_and_shows_delta():
    rng = np.random.default_rng(42)
    it = rng.uniform(3000.0, 7000.0, size=N_STEPS)
    cool = it * 0.32

    # 基线：无储能（充放电为 0），电网=设施（不含储能损耗）。
    base_grid = (it + cool) * 1.03
    base = _make_schedule(it, cool, _zeros(), _zeros(), base_grid, "base")

    # 优化：削峰充放电，电网峰值下降但引入往返损耗。
    charge = np.where(base_grid < base_grid.mean(), 300.0, 0.0)
    discharge = np.where(base_grid > base_grid.mean(), 300.0, 0.0)
    opt_grid = base_grid + charge - discharge  # 仅示意，电网口径不影响 ΔPUE
    opt = _make_schedule(it, cool, charge, discharge, opt_grid, "opt")

    res = pue_with_vs_without_storage(it, cool, opt, base, ups_loss_ratio=0.03)

    # 关键契约：储能不得声称改善 PUE —— ΔPUE >= 0。
    assert res["delta_pue"] >= 0.0
    assert res["pue_optimized"] >= res["pue_baseline"]
    assert res["pue_baseline"] >= 1.0
    # 并列量化：电网 kWh 差异与 PUE 差异都返回。
    for k in ("grid_kwh_optimized", "grid_kwh_baseline", "delta_grid_kwh"):
        assert np.isfinite(res[k])
    # 基线无储能损耗 → 基线 PUE 恰为纯设施口径。
    assert np.isclose(res["pue_baseline"], float(np.mean((it + cool) * 1.03 / it)))
    assert "PUE" in res["interpretation"]


# --------------------------------------------------------------------------
# 6. 设施功率分解
# --------------------------------------------------------------------------
def test_decompose_components_sum_to_facility():
    it = np.full(N_STEPS, 3000.0)
    cool = it * 0.32
    charge = np.full(N_STEPS, 200.0)
    discharge = np.full(N_STEPS, 150.0)
    sched = _make_schedule(it, cool, charge, discharge, it + cool, "opt")

    comp = decompose_facility_power(it, cool, sched, ups_loss_ratio=0.03)
    assert set(comp.keys()) == {"it", "cooling", "ups_loss", "battery_loss"}

    # it 分量精确等于输入。
    assert np.allclose(comp["it"], it)
    # 四分量之和 = (it+cool)*(1+ups) + battery_loss。
    battery_expected = charge * 0.05 + discharge * (1.0 / 0.95 - 1.0)
    total = comp["it"] + comp["cooling"] + comp["ups_loss"] + comp["battery_loss"]
    expected = (it + cool) * 1.03 + battery_expected
    assert np.allclose(total, expected)


# --------------------------------------------------------------------------
# 7. 提升杠杆清单：有序、含区间、含 [INFERENCE]
# --------------------------------------------------------------------------
def test_levers_ordered_and_capped():
    levers = pue_improvement_levers()
    assert isinstance(levers, list) and len(levers) >= 5
    # 每条含名称、区间、原理。
    for lv in levers:
        assert {"name", "pue_reduction_pct", "mechanism"} <= set(lv.keys())
        lo, hi = lv["pue_reduction_pct"]
        assert lo <= hi
    # 按预期效果（区间上界）降序排列。
    upper = [lv["pue_reduction_pct"][1] for lv in levers]
    assert upper == sorted(upper, reverse=True)
    # 储能选址条必须诚实反映「不改善甚至略升」。
    storage = next(lv for lv in levers if "储能" in lv["name"])
    assert storage["pue_reduction_pct"][1] <= 0.0