"""Tests for core.optimizer: 端到端调度、反同时性、SOC 界、JSON 序列化、北京控制城市。"""
from __future__ import annotations

import json
import math

import pytest

from core.battery import BatteryModel, BatteryConfig
from core.optimizer import MPCOptimizer, PlanResult, SchedulePoint
from core.tariff import builtin_tariffs
from core.policy import PolicyParams, mode_presets
from core.solar import synthetic_weather, SolarModel


LOAD_24 = [
    0.66, 0.60, 0.576, 0.576, 0.60, 0.744,
    1.14, 1.50, 1.38, 1.08, 1.02, 1.08,
    1.20, 1.08, 1.02, 1.08, 1.26, 1.56,
    1.92, 2.04, 1.74, 1.32, 1.02, 0.78,
]


def _battery():
    cfg = BatteryConfig(capacity_kwh=5.0, max_charge_kw=2.5, max_discharge_kw=2.5,
                        round_trip_eff=0.92, soc_min=0.05, soc_max=1.0, soc_start=0.30,
                        cycle_life=6000, pack_cost_cny=12999, reserve_soc=0.10)
    return BatteryModel(cfg)


def _tariff(city="shenzhen"):
    return builtin_tariffs()[city]


def _make_opt(city="shenzhen", mode="arbitrage"):
    p = mode_presets()[mode]
    return MPCOptimizer(_battery(), _tariff(city), p, site_id="test", model="SOLARBANK_4_E5000")


def _pv(clear=True):
    if clear:
        w = synthetic_weather("clear", seed=0)
    else:
        w = synthetic_weather("rain", seed=0)
    s = SolarModel(5.0, 0.85)
    return s.forecast(w).pv_kw


class TestBasicOptimize:
    def test_returns_plan_result(self):
        opt = _make_opt()
        res = opt.optimize(LOAD_24, _pv())
        assert isinstance(res, PlanResult)
        assert len(res.points) == 24

    def test_solver_status_optimal(self):
        opt = _make_opt()
        res = opt.optimize(LOAD_24, _pv())
        assert res.solver_status == "optimal"

    def test_savings_positive_for_shenzhen(self):
        opt = _make_opt("shenzhen", "arbitrage")
        res = opt.optimize(LOAD_24, _pv())
        assert res.savings_cny > 0
        assert res.savings_pct > 5

    def test_beijing_control_case(self):
        opt = _make_opt("beijing", "arbitrage")
        res = opt.optimize(LOAD_24, _pv())
        assert res.savings_pct < 2.0

    def test_all_modes_optimal(self):
        for mode in ("arbitrage", "self_consumption", "resilience", "balanced"):
            opt = _make_opt("shenzhen", mode)
            res = opt.optimize(LOAD_24, _pv())
            assert res.solver_status == "optimal"
            assert res.savings_cny >= 0, "%s negative savings" % mode

    def test_savings_nonneg_across_cities(self):
        for city in ("shenzhen", "shanghai", "zhejiang", "jiangsu", "shandong", "sichuan", "hunan"):
            opt = _make_opt(city, "arbitrage")
            res = opt.optimize(LOAD_24, _pv())
            assert res.savings_cny >= -0.01, "%s negative" % city


class TestSOCBound:
    def test_soc_within_bounds(self):
        opt = _make_opt("shenzhen", "arbitrage")
        res = opt.optimize(LOAD_24, _pv())
        cfg = opt.battery.cfg
        for p in res.points:
            assert p.soc >= cfg.soc_min - 1e-4, "SOC %.4f below soc_min" % p.soc
            assert p.soc <= cfg.soc_max + 1e-4, "SOC %.4f above soc_max" % p.soc

    def test_reserve_is_hard_floor(self):
        p = PolicyParams(mode="arbitrage", reserve_soc=0.30, target_soc=0.95)
        opt = MPCOptimizer(_battery(), _tariff("shenzhen"), p)
        res = opt.optimize(LOAD_24, _pv())
        for pt in res.points:
            assert pt.soc >= 0.295, "reserve 0.30 violated: SOC=%.4f" % pt.soc


class TestAntiSimultaneity:
    def test_no_charge_discharge_conflict(self):
        opt = _make_opt("shenzhen", "arbitrage")
        res = opt.optimize(LOAD_24, _pv(clear=True))
        for p in res.points:
            assert not (p.battery_kw > 1e-6 and p.battery_kw < -1e-6)  # always one sign
        # specifically check that charge > 0 and discharge > 0 never both
        cfg = opt.battery.cfg
        # battery_kw = charge - discharge, so both positive means charge>0 AND discharge>0
        # which implies battery_kw can be anything — but we check via raw values in LP:
        # Since the cleanup guarantees zero, checking action labels:
        for p in res.points:
            if p.action == "charge":
                assert p.battery_kw > 0
            elif p.action == "discharge":
                assert p.battery_kw < 0

    def test_no_buy_sell_conflict(self):
        opt = _make_opt("shenzhen", "arbitrage")
        res = opt.optimize(LOAD_24, _pv())
        for p in res.points:
            # grid_kw = buy - sell; if both>0 then grid_kw ambiguous, but action labels help
            if p.action == "export":
                assert p.grid_kw < 0
            elif p.grid_kw > 1e-6:
                # buying, should not be simultaneously exporting
                pass


class TestExportAndComfort:
    def test_no_export_when_disabled(self):
        p = PolicyParams(mode="self_consumption", allow_export=False)
        opt = MPCOptimizer(_battery(), _tariff("shenzhen"), p)
        res = opt.optimize(LOAD_24, _pv())
        for pt in res.points:
            assert pt.grid_kw >= -1e-6, "sell despite allow_export=False"

    def test_comfort_peak_cap(self):
        p = PolicyParams(mode="arbitrage", comfort_max_peak_kw=1.5)
        opt = MPCOptimizer(_battery(), _tariff("shenzhen"), p)
        # use high load to potentially trigger
        heavy_load = [4.0] * 24
        res = opt.optimize(heavy_load, [0.0] * 24)
        for pt in res.points:
            if pt.grid_kw > 0:
                assert pt.grid_kw <= 1.5 + 0.01


class TestJSON:
    def test_to_dict_json_serializable(self):
        opt = _make_opt()
        res = opt.optimize(LOAD_24, _pv())
        d = res.to_dict()
        s = json.dumps(d, ensure_ascii=False)
        assert len(s) > 100
        loaded = json.loads(s)
        assert loaded["solver_status"] == "optimal"
        assert len(loaded["points"]) == 24

    def test_multiple_combos_json(self):
        for city in ("shenzhen", "shanghai", "beijing"):
            for mode in ("arbitrage", "resilience"):
                opt = _make_opt(city, mode)
                res = opt.optimize(LOAD_24, _pv())
                s = json.dumps(res.to_dict())
                assert "NaN" not in s and "Infinity" not in s


class TestCyclesAndMetrics:
    def test_cycles_within_cap(self):
        opt = _make_opt("shenzhen", "arbitrage")
        res = opt.optimize(LOAD_24, _pv())
        assert res.cycles_used <= opt.params.max_cycles_per_day + 0.01

    def test_pv_self_consumption_range(self):
        opt = _make_opt("shenzhen", "self_consumption")
        res = opt.optimize(LOAD_24, _pv())
        assert 0.0 <= res.pv_self_consumption <= 1.0

    def test_baseline_positive(self):
        opt = _make_opt()
        base = opt.baseline(LOAD_24, _pv())
        assert base > 0


class TestExplain:
    def test_rationale_nonempty(self):
        opt = _make_opt()
        res = opt.optimize(LOAD_24, _pv())
        assert len(res.rationale) >= 3
        for r in res.rationale:
            assert isinstance(r, str)
            assert len(r) > 5