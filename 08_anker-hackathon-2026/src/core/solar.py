"""天气→光伏出力预测:辐照模型、温度降额、置信度,以及确定性合成天气。

pv_kw = capacity_kwp * derate * (ghi/1000) * (1 - 0.75*cloud) * temp_factor
temp_factor 在环境温度 >25°C 时每 °C 降 0.4%,下限 0.25;出力另受
额定*derate 与 0 的夹逼。synthetic_weather 由 (day, seed) 唯一决定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import random

# 组件温度相对环境温度的典型温升(°C),用于 temp_factor
_CELL_RISE_C = 25.0
# 每 °C (电池片温度超过 25°C) 的功率降额
_TEMP_DERATE_PER_C = 0.004
_TEMP_FACTOR_FLOOR = 0.25


@dataclass
class WeatherForecast:
    hours: List[float]                # 0..23
    cloud_cover: List[float]          # 0..1
    temp_c: List[float]
    ghi_wm2: List[float]              # 水平面辐照 W/m²
    precipitation: List[float] = field(default_factory=list)


@dataclass
class SolarForecast:
    hours: List[float]
    pv_kw: List[float]                # 逐时预测出力
    confidence: List[float]           # 0..1,用于鲁棒优化


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class SolarModel:
    def __init__(self, capacity_kwp: float, tilt_derate: float = 0.85) -> None:
        if capacity_kwp <= 0:
            raise ValueError("capacity_kwp must be > 0")
        self.capacity_kwp = float(capacity_kwp)
        self.derate = float(tilt_derate)

    def temp_factor(self, temp_c: float) -> float:
        """0.4%/°C 降额,以电池片温度 ≈ 环境 + 25°C 估算,下限 0.25。"""
        cell_c = temp_c + _CELL_RISE_C
        factor = 1.0 - _TEMP_DERATE_PER_C * max(0.0, cell_c - 25.0)
        return max(_TEMP_FACTOR_FLOOR, factor)

    def forecast(self, weather: WeatherForecast) -> SolarForecast:
        n = len(weather.hours)
        for name in ("cloud_cover", "temp_c", "ghi_wm2"):
            seq = getattr(weather, name)
            if len(seq) != n:
                raise ValueError("weather.%s length %d != hours length %d" % (name, len(seq), n))
        precip = weather.precipitation if len(weather.precipitation) == n else [0.0] * n
        cap = self.capacity_kwp * self.derate
        pv_kw: List[float] = []
        conf: List[float] = []
        for i in range(n):
            ghi = max(0.0, weather.ghi_wm2[i])
            cloud = _clamp(weather.cloud_cover[i], 0.0, 1.0)
            f = (ghi / 1000.0) * (1.0 - 0.75 * cloud) * self.temp_factor(weather.temp_c[i])
            pv_kw.append(_clamp(cap * f, 0.0, cap))
            conf.append(_clamp(1.0 - 0.6 * cloud - 0.3 * max(0.0, precip[i]), 0.3, 1.0))
        return SolarForecast(hours=list(weather.hours), pv_kw=pv_kw, confidence=conf)

    def energy_kwh(self, fc: SolarForecast) -> float:
        """逐时平均功率 kW × 1h ⇒ 数值即 kWh。"""
        return sum(max(0.0, p) for p in fc.pv_kw)


# 各天象 profile: ghi 峰值 / 半宽 / 云量 / 温度峰值 / 夜间云底 / 降水
_PROFILES = {
    "clear":     {"ghi_peak": 950.0, "width": 3.0, "cloud": 0.10, "t_peak": 31.5, "t_night": 24.0, "cloud_night": 0.12, "rain": 0.0},
    "heatwave":  {"ghi_peak": 1000.0, "width": 2.8, "cloud": 0.05, "t_peak": 40.0, "t_night": 30.0, "cloud_night": 0.05, "rain": 0.0},
    "cloudy":    {"ghi_peak": 575.0, "width": 3.4, "cloud": 0.45, "t_peak": 28.0, "t_night": 22.0, "cloud_night": 0.50, "rain": 0.0},
    "overcast":  {"ghi_peak": 250.0, "width": 3.8, "cloud": 0.82, "t_peak": 24.0, "t_night": 19.0, "cloud_night": 0.85, "rain": 0.0},
    "rain":      {"ghi_peak": 140.0, "width": 4.0, "cloud": 0.90, "t_peak": 22.0, "t_night": 18.0, "cloud_night": 0.92, "rain": 1.0},
}


def synthetic_weather(day: str, seed: int = 0) -> WeatherForecast:
    """确定性合成 24h 天气。day ∈ clear/cloudy/overcast/rain/heatwave。"""
    if day not in _PROFILES:
        raise ValueError("unknown weather day %r; choose from %s" % (day, sorted(_PROFILES)))
    prof = _PROFILES[day]
    rng = random.Random("%s|%d" % (day, seed))
    hours = [float(h) for h in range(24)]
    ghi: List[float] = []
    cloud: List[float] = []
    temp: List[float] = []
    precip: List[float] = []
    for h in hours:
        # 日出 ~6.0,日落 ~18.5,午峰 ~12.5
        if 6.0 < h < 18.5:
            g = prof["ghi_peak"] * (rng.uniform(0.94, 1.06) if prof["rain"] == 0.0 else rng.uniform(0.6, 1.2))
            g *= max(0.0, 1.0 - ((h - 12.5) / prof["width"]) ** 2)
            ghi.append(max(0.0, g))
        else:
            ghi.append(0.0)
        base_cloud = prof["cloud"] if 6.0 < h < 18.5 else prof["cloud_night"]
        cloud.append(_clamp(base_cloud + rng.uniform(-0.04, 0.04), 0.0, 0.95))
        if 5.0 <= h <= 17.0:
            t = prof["t_night"] + (prof["t_peak"] - prof["t_night"]) * max(0.0, 1.0 - ((h - 14.0) / 6.0) ** 2)
        else:
            t = prof["t_night"] - 1.5
        temp.append(t + rng.uniform(-0.5, 0.5))
        if prof["rain"] > 0.0 and 7 <= h <= 19:
            precip.append(rng.uniform(0.3, 2.2))
        elif prof["rain"] > 0.0 and rng.random() < 0.3:
            precip.append(rng.uniform(0.1, 0.8))
        else:
            precip.append(0.0)
    return WeatherForecast(hours=hours, cloud_cover=cloud, temp_c=temp, ghi_wm2=ghi, precipitation=precip)