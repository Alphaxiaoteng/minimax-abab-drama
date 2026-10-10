"""Tests for core.tariff: 8 城市分时电价、跨零点解析、JSON 读写。"""
from __future__ import annotations

import json
import math
import os
import tempfile

import pytest

from core.tariff import (
    TariffTier, TariffPlan, builtin_tariffs, load_tariff, save_tariff, TIER_NAMES,
)


CITIES = ("shenzhen", "shanghai", "jiangsu", "zhejiang", "beijing", "shandong", "sichuan", "hunan")


class TestBuiltinTariffs:
    def test_at_least_8_cities(self):
        plans = builtin_tariffs()
        assert len(plans) >= 8

    def test_all_required_cities_present(self):
        plans = builtin_tariffs()
        for city in CITIES:
            assert city in plans, "missing city %r" % city

    def test_each_plan_has_tiers_and_export(self):
        for city, plan in builtin_tariffs().items():
            assert len(plan.tiers) >= 1, "%s has no tiers" % city
            assert plan.export_price > 0, "%s missing export_price" % city
            assert plan.currency == "CNY"

    def test_tier_order_sorted_cheapest_to_most_expensive(self):
        for city, plan in builtin_tariffs().items():
            if not plan.tier_order:
                continue
            prices = []
            for name in plan.tier_order:
                p = min(t.price for t in plan.tiers if t.name == name)
                prices.append(p)
            assert prices == sorted(prices), "%s tier_order not monotonic" % city

    def test_shenzhen_spread_is_08635(self):
        plans = builtin_tariffs()
        sz = plans["shenzhen"]
        assert sz.spread() == pytest.approx(0.8635, abs=1e-4)

    def test_beijing_spread_is_zero(self):
        plans = builtin_tariffs()
        bj = plans["beijing"]
        assert bj.spread() == pytest.approx(0.0, abs=1e-9)
        assert len(bj.tier_order) == 1

    def test_no_negative_prices(self):
        for city, plan in builtin_tariffs().items():
            for tier in plan.tiers:
                assert tier.price >= 0, "%s/%s negative" % (city, tier.name)


class TestCrossMidnight:
    def test_zhejiang_valley_at_23_5(self):
        plan = builtin_tariffs()["zhejiang"]
        assert plan.tier_at(23.5) == "valley"
        assert plan.price_at(23.5) == pytest.approx(0.288)

    def test_zhejiang_valley_at_3_0(self):
        plan = builtin_tariffs()["zhejiang"]
        assert plan.tier_at(3.0) == "valley"

    def test_beijing_flat_always(self):
        plan = builtin_tariffs()["beijing"]
        for h in range(24):
            assert plan.tier_at(h) == "flat"
            assert plan.price_at(h) == pytest.approx(0.4883)

    def test_shandong_cross_midnight(self):
        plan = builtin_tariffs()["shandong"]
        assert plan.tier_at(23.0) == "valley"
        assert plan.tier_at(5.0) == "valley"
        assert plan.tier_at(12.0) == "peak"


class TestDailyCurve:
    def test_curve_length(self):
        plan = builtin_tariffs()["shenzhen"]
        curve = plan.daily_curve(0.25)
        assert len(curve) == 96

    def test_curve_covers_all_hours(self):
        plan = builtin_tariffs()["shanghai"]
        curve = plan.daily_curve(1.0)
        assert len(curve) == 24
        for hh, price, tier in curve:
            assert price > 0
            assert tier in TIER_NAMES


class TestLoadSave:
    def test_roundtrip(self):
        plan = builtin_tariffs()["shenzhen"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_tariff(plan, path)
            loaded = load_tariff(path)
            assert loaded.city == plan.city
            assert loaded.export_price == plan.export_price
            assert len(loaded.tiers) == len(plan.tiers)
            assert loaded.spread() == pytest.approx(plan.spread())
        finally:
            os.unlink(path)

    def test_malformed_json_raises_value_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            path = f.name
        try:
            with pytest.raises(ValueError, match="not valid JSON"):
                load_tariff(path)
        finally:
            os.unlink(path)

    def test_missing_tiers_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"city": "test", "export_price": 0.4}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="missing required field"):
                load_tariff(path)
        finally:
            os.unlink(path)

    def test_empty_tiers_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"city": "test", "export_price": 0.4, "tiers": []}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="non-empty"):
                load_tariff(path)
        finally:
            os.unlink(path)

    def test_non_numeric_price_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"city": "x", "export_price": 0.4,
                       "tiers": [{"name": "flat", "start_hour": 0, "end_hour": 24, "price": "bad"}]}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="non-numeric"):
                load_tariff(path)
        finally:
            os.unlink(path)


class TestWindows:
    def test_valley_windows(self):
        plan = builtin_tariffs()["zhejiang"]
        wins = plan.windows("valley")
        assert len(wins) >= 1
        s, e = wins[0]
        assert e > 24 or e > s