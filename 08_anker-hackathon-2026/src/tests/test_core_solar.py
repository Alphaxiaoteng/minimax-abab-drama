"""Tests for core.solar: 出力预测公式、合成天气确定性、温度降额、置信度。"""
from __future__ import annotations

import math

import pytest

from core.solar import (
    WeatherForecast, SolarForecast, SolarModel, synthetic_weather,
)


class TestSolarForecast:
    def test_pv_zero_at_night(self):
        w = WeatherForecast(hours=[0.0, 12.0], cloud_cover=[0.1, 0.1],
                            temp_c=[20.0, 30.0], ghi_wm2=[0.0, 900.0])
        s = SolarModel(capacity_kwp=5.0, tilt_derate=0.85)
        fc = s.forecast(w)
        assert fc.pv_kw[0] == pytest.approx(0.0)
        assert fc.pv_kw[1] > 0

    def test_pv_capped_at_nameplate_derate(self):
        w = WeatherForecast(hours=[12.0], cloud_cover=[0.0],
                            temp_c=[20.0], ghi_wm2=[2000.0])
        s = SolarModel(capacity_kwp=5.0, tilt_derate=0.85)
        fc = s.forecast(w)
        assert fc.pv_kw[0] <= 5.0 * 0.85 + 1e-6

    def test_temp_derating_above_25(self):
        s = SolarModel(capacity_kwp=5.0, tilt_derate=1.0)
        w_cool = WeatherForecast(hours=[12.0], cloud_cover=[0.0],
                                 temp_c=[25.0], ghi_wm2=[1000.0])
        w_hot = WeatherForecast(hours=[12.0], cloud_cover=[0.0],
                                temp_c=[45.0], ghi_wm2=[1000.0])
        fc_cool = s.forecast(w_cool)
        fc_hot = s.forecast(w_hot)
        assert fc_hot.pv_kw[0] < fc_cool.pv_kw[0]

    def test_cloud_reduces_output(self):
        s = SolarModel(capacity_kwp=5.0, tilt_derate=1.0)
        w_clear = WeatherForecast(hours=[12.0], cloud_cover=[0.0],
                                  temp_c=[25.0], ghi_wm2=[1000.0])
        w_cloudy = WeatherForecast(hours=[12.0], cloud_cover=[0.5],
                                   temp_c=[25.0], ghi_wm2=[1000.0])
        assert s.forecast(w_cloudy).pv_kw[0] < s.forecast(w_clear).pv_kw[0]

    def test_confidence_range(self):
        s = SolarModel(capacity_kwp=5.0)
        w = WeatherForecast(hours=[12.0], cloud_cover=[0.8], temp_c=[25.0],
                            ghi_wm2=[500.0], precipitation=[2.0])
        fc = s.forecast(w)
        assert 0.3 <= fc.confidence[0] <= 1.0

    def test_energy_kwh_sums(self):
        s = SolarModel(capacity_kwp=5.0)
        w = WeatherForecast(hours=[10.0, 11.0, 12.0], cloud_cover=[0.1]*3,
                            temp_c=[25.0]*3, ghi_wm2=[800.0, 900.0, 950.0])
        fc = s.forecast(w)
        assert s.energy_kwh(fc) == pytest.approx(sum(fc.pv_kw))


class TestSyntheticWeather:
    ALL_DAYS = ("clear", "cloudy", "overcast", "rain", "heatwave")

    def test_deterministic(self):
        for d in self.ALL_DAYS:
            w1 = synthetic_weather(d, seed=42)
            w2 = synthetic_weather(d, seed=42)
            assert w1.ghi_wm2 == w2.ghi_wm2
            assert w1.cloud_cover == w2.cloud_cover
            assert w1.temp_c == w2.temp_c

    def test_length_24(self):
        for d in self.ALL_DAYS:
            w = synthetic_weather(d, seed=0)
            assert len(w.hours) == 24
            assert len(w.ghi_wm2) == 24
            assert len(w.cloud_cover) == 24
            assert len(w.temp_c) == 24
            assert len(w.precipitation) == 24

    def test_clear_peak_gt_900(self):
        w = synthetic_weather("clear", seed=1)
        assert max(w.ghi_wm2) > 900

    def test_heatwave_high_temp(self):
        w = synthetic_weather("heatwave", seed=1)
        assert max(w.temp_c) > 38

    def test_rain_has_precipitation(self):
        w = synthetic_weather("rain", seed=1)
        nz = sum(1 for p in w.precipitation if p > 0)
        assert nz >= 8

    def test_non_rain_zero_precipitation(self):
        for d in ("clear", "cloudy", "overcast", "heatwave"):
            w = synthetic_weather(d, seed=0)
            assert all(p == 0.0 for p in w.precipitation)

    def test_cloud_ordering(self):
        clear_w = synthetic_weather("clear", seed=0)
        overcast_w = synthetic_weather("overcast", seed=0)
        assert max(clear_w.cloud_cover) < max(overcast_w.cloud_cover)

    def test_ghi_ordering(self):
        peaks = {}
        for d in self.ALL_DAYS:
            w = synthetic_weather(d, seed=0)
            peaks[d] = max(w.ghi_wm2)
        assert peaks["clear"] > peaks["cloudy"] > peaks["overcast"] > peaks["rain"]

    def test_unknown_day_raises(self):
        with pytest.raises(ValueError, match="unknown weather"):
            synthetic_weather("blizzard", seed=0)

    def test_night_ghi_zero(self):
        w = synthetic_weather("clear", seed=0)
        for i in range(24):
            if w.hours[i] < 6 or w.hours[i] > 19:
                assert w.ghi_wm2[i] == pytest.approx(0.0)