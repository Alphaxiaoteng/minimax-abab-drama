"""Tests for core.hardware: 规格库完整性、无 Matter、可控性正确、聚合拓扑。"""
from __future__ import annotations

import pytest

from core.hardware import (
    DeviceSpec, HardwareCatalog, HomeLoad, SiteConfig, demo_site,
)


REQUIRED_MODELS = [
    "SOLIX_C1000_GEN2", "SOLIX_C2000_GEN2", "SOLIX_S2000", "SOLIX_F2600",
    "SOLIX_F3800", "SOLIX_F3800_PLUS", "SOLIX_E10",
    "SOLARBANK_4_E5000", "XE", "SOLARBANK_MAX_AC", "X1", "SOLARBANK_2_E1600",
]

CONTROLLABLE_MODELS = ["SOLARBANK_4_E5000", "SOLARBANK_MAX_AC", "XE"]


@pytest.fixture
def catalog():
    return HardwareCatalog()


class TestCatalog:
    def test_all_models_present(self, catalog):
        ms = catalog.models()
        for m in REQUIRED_MODELS:
            assert m in ms, "missing model %s" % m

    def test_no_matter_anywhere(self, catalog):
        for m in catalog.models():
            spec = catalog.get(m)
            assert "matter" not in spec.comms, "%s has Matter" % m

    def test_all_specs_nonempty_comms(self, catalog):
        for m in catalog.models():
            spec = catalog.get(m)
            assert len(spec.comms) > 0, "%s empty comms" % m

    def test_all_specs_positive_capacity(self, catalog):
        for m in catalog.models():
            assert catalog.get(m).capacity_kwh > 0

    def test_controllable_set(self, catalog):
        controllables = sorted(m for m in catalog.models() if catalog.get(m).controllable)
        assert controllables == sorted(CONTROLLABLE_MODELS)

    def test_f3800_not_controllable(self, catalog):
        spec = catalog.get("SOLIX_F3800")
        assert spec.controllable is False
        assert "modbus" not in spec.comms

    def test_e5000_has_modbus(self, catalog):
        assert "modbus" in catalog.get("SOLARBANK_4_E5000").comms

    def test_x1_not_controllable(self, catalog):
        assert catalog.get("X1").controllable is False

    def test_unknown_model_raises(self, catalog):
        with pytest.raises(ValueError, match="unknown model"):
            catalog.get("NONEXISTENT")


class TestBatteryConfig:
    def test_from_model(self, catalog):
        cfg = catalog.battery_config("SOLARBANK_4_E5000")
        assert cfg.capacity_kwh == pytest.approx(5.024)
        assert cfg.max_charge_kw > 0

    def test_soc_start_override(self, catalog):
        cfg = catalog.battery_config("XE", soc_start=0.60)
        assert cfg.soc_start == 0.60


class TestAggregate:
    def test_sum_capacity(self, catalog):
        cfg = catalog.aggregate(["SOLARBANK_4_E5000", "XE"])
        assert cfg.capacity_kwh == pytest.approx(5.024 + 7.0)
        assert cfg.max_charge_kw == pytest.approx(2.5 + 5.0)

    def test_empty_raises(self, catalog):
        with pytest.raises(ValueError):
            catalog.aggregate([])


class TestDemoSite:
    def test_controllable_model(self):
        site = demo_site()
        cat = HardwareCatalog()
        assert cat.get(site.model).controllable

    def test_shenzhen(self):
        assert demo_site().tariff_city == "shenzhen"

    def test_capacity_matches_spec(self):
        site = demo_site()
        cat = HardwareCatalog()
        assert site.capacity_kwh == pytest.approx(cat.get(site.model).capacity_kwh)


class TestHomeLoad:
    def test_profile_length(self):
        hl = HomeLoad(base_kw=1.5)
        assert len(hl.hourly_profile) == 24

    def test_series_values(self):
        hl = HomeLoad(base_kw=2.0)
        s = hl.series()
        assert len(s) == 24
        assert all(v > 0 for v in s)