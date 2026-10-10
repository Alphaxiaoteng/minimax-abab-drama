"""测试 src/workload.py —— IT 负载、制冷、环境温度、峰值统计。"""
from __future__ import annotations

import numpy as np
import pytest

from src.config import N_STEPS, default_scenarios, Scenario
from src.workload import (
    ambient_profile,
    generate_cooling,
    generate_it_power,
    spike_stats,
)


# --------------------------------------------------------------------------
# Shape / length
# --------------------------------------------------------------------------
def test_it_power_shape():
    for sc in default_scenarios():
        it = generate_it_power(sc)
        assert it.shape == (N_STEPS,)
        assert it.dtype == np.float64


def test_cooling_shape():
    sc = default_scenarios()[0]
    it = generate_it_power(sc)
    cool = generate_cooling(it, sc)
    assert cool.shape == (N_STEPS,)
    assert cool.dtype == np.float64


def test_ambient_shape():
    amb = ambient_profile()
    assert amb.shape == (N_STEPS,)
    assert amb.dtype == np.float64


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_determinism_same_seed():
    sc = default_scenarios()[1]
    a = generate_it_power(sc)
    b = generate_it_power(sc)
    np.testing.assert_array_equal(a, b)


def test_determinism_different_seed():
    sc1 = Scenario(name="a", seed=100, spike_count=6, spike_scale=0.55)
    sc2 = Scenario(name="b", seed=999, spike_count=6, spike_scale=0.55)
    a = generate_it_power(sc1)
    b = generate_it_power(sc2)
    assert not np.array_equal(a, b)


# --------------------------------------------------------------------------
# Bounds / positivity
# --------------------------------------------------------------------------
def test_it_power_upper_bound():
    for sc in default_scenarios():
        it = generate_it_power(sc)
        assert it.max() <= sc.datacenter.it_peak_kw + 1e-9


def test_it_power_positive():
    for sc in default_scenarios():
        it = generate_it_power(sc)
        assert (it > 0).all()


def test_cooling_positive():
    for sc in default_scenarios():
        it = generate_it_power(sc)
        cool = generate_cooling(it, sc)
        assert (cool > 0).all()


# --------------------------------------------------------------------------
# Scenario differentiation
# --------------------------------------------------------------------------
def test_extreme_larger_than_baseline():
    sc_base = default_scenarios()[0]
    sc_ext = default_scenarios()[2]
    it_base = generate_it_power(sc_base)
    it_ext = generate_it_power(sc_ext)
    assert it_ext.max() > it_base.max()


def test_transient_spikes_larger_than_baseline():
    sc_base = default_scenarios()[0]
    sc_trans = default_scenarios()[1]
    it_base = generate_it_power(sc_base)
    it_trans = generate_it_power(sc_trans)
    assert it_trans.max() > it_base.max()


# --------------------------------------------------------------------------
# PUE 物理合理性
# --------------------------------------------------------------------------
def test_pue_without_storage_in_range():
    """无储能时 facility/IT PUE 应落在 1.3 ~ 1.6。"""
    sc = default_scenarios()[0]
    it = generate_it_power(sc)
    cool = generate_cooling(it, sc)
    dc = sc.datacenter
    ups_loss = dc.ups_loss_ratio * (it + cool)
    facility = it + cool + ups_loss
    pue = facility / it
    assert 1.3 <= pue.mean() <= 1.6


# --------------------------------------------------------------------------
# spike_stats
# --------------------------------------------------------------------------
def test_spike_stats_keys():
    sc = default_scenarios()[1]
    it = generate_it_power(sc)
    st = spike_stats(it, sc.datacenter.it_base_kw)
    assert "spike_events" in st
    assert "max_spike_kw" in st
    assert "transient_energy_kwh" in st
    assert "duty" in st


def test_spike_stats_baseline_events():
    sc = default_scenarios()[0]
    it = generate_it_power(sc)
    st = spike_stats(it, sc.datacenter.it_base_kw)
    assert st["spike_events"] >= 1


def test_spike_stats_transient_more_events():
    sc_base = default_scenarios()[0]
    sc_trans = default_scenarios()[1]
    st_base = spike_stats(generate_it_power(sc_base), sc_base.datacenter.it_base_kw)
    st_trans = spike_stats(generate_it_power(sc_trans), sc_trans.datacenter.it_base_kw)
    assert st_trans["spike_events"] >= st_base["spike_events"]


def test_spike_stats_types():
    sc = default_scenarios()[2]
    it = generate_it_power(sc)
    st = spike_stats(it, sc.datacenter.it_base_kw)
    assert isinstance(st["spike_events"], (int, float))
    assert isinstance(st["max_spike_kw"], float)
    assert isinstance(st["transient_energy_kwh"], float)
    assert 0.0 <= st["duty"] <= 1.0


# --------------------------------------------------------------------------
# Ambient profile
# --------------------------------------------------------------------------
def test_ambient_no_seed_deterministic():
    a = ambient_profile()
    b = ambient_profile()
    np.testing.assert_array_equal(a, b)


def test_ambient_range():
    amb = ambient_profile()
    assert amb.max() <= 40.0
    assert amb.min() >= 15.0


def test_ambient_peaks_afternoon():
    """环境温度峰值应出现在午后 14~17 点区间 (steps 56~68)。"""
    amb = ambient_profile()
    peak_idx = int(np.argmax(amb))
    assert 52 <= peak_idx <= 72


# --------------------------------------------------------------------------
# 打印 spike_stats（供报告参考）
# --------------------------------------------------------------------------
def test_print_spike_stats():
    """打印三个情景的 spike_stats，pytest -s 时可见。"""
    print("\n=== Spike Statistics ===")
    for sc in default_scenarios():
        it = generate_it_power(sc)
        st = spike_stats(it, sc.datacenter.it_base_kw)
        print(f"{sc.name}: events={st['spike_events']:.0f}, "
              f"max={st['max_spike_kw']:.1f} kW, "
              f"energy={st['transient_energy_kwh']:.1f} kWh, "
              f"duty={st['duty']:.3f}")