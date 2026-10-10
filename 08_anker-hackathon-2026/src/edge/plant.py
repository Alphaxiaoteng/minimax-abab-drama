"""数字孪生 (PlantSimulator):Anker 户储站点的实时仿真替身。

每步依次:物理功率夹紧 → 电池模型步进 → 负荷/PV/电网/温度合成 → SiteReading。
run_closed_loop 演示 15 分钟级滚动 MPC 重规划,是核心卖点演示循环。
仅依赖标准库与 core,可在边缘设备离线运行。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

from core.battery import BatteryModel, BatteryState
from core.hardware import HomeLoad
from core.optimizer import SchedulePoint
from core.policy import PolicyParams
from core.solar import SolarForecast, SolarModel, WeatherForecast
from core.tariff import TariffPlan


@dataclass
class SiteReading:
    ts: float
    hour: float
    soc: float
    pv_kw: float
    load_kw: float
    battery_kw: float
    grid_kw: float
    price: float
    tier: str
    temp_c: float

    def to_row(self) -> Dict[str, object]:
        return dict(asdict(self))


class PlantSimulator:
    """站级数字孪生:电池 + 家庭负荷 + 光伏 + 电网 + 温度。"""

    SELF_HEAT_K = 6.0      # 满功率放热 (°C)
    HOLD_HEAT_K = 1.5      # 每待机小时附加温升 (°C)
    HOLD_HEAT_CAP_H = 10.0 # 待机热累积上限 (小时)
    CLOUD_P = 0.08         # 每步出现云遮挡的概率
    CLOUD_FACTOR = 0.25    # ±25% PV 扰动

    def __init__(self, battery: BatteryModel, load: HomeLoad, solar: SolarModel,
                 weather: WeatherForecast, tariff: TariffPlan, seed: int = 1) -> None:
        self.battery = battery
        self.load = load
        self.solar = solar
        self.weather = weather
        self.tariff = tariff
        self.seed = int(seed)
        self._pv_fc: SolarForecast = solar.forecast(weather)
        self._state: BatteryState = BatteryState(
            soc=battery.cfg.soc_start, soh=1.0, cycles=0.0, temp_c=25.0)
        self._t: float = 0.0
        self._held_h: float = 0.0
        self._faults: set = set()

    @property
    def state(self) -> BatteryState:
        return self._state

    # ---------- 基础模型 ----------

    def _hourly_load_kw(self, hour: float) -> float:
        h = int(round(hour)) % 24
        rng = random.Random(self.seed + int(hour * 100))
        noise = 1.0 + rng.uniform(-0.06, 0.06)
        prof = self.load.hourly_profile[h] if self.load.hourly_profile else 1.0
        return max(0.0, prof * self.load.base_kw * noise)

    def _hourly_pv_kw(self, hour: float, noise: bool = True) -> float:
        h = int(round(hour)) % 24
        pv = self._pv_fc.pv_kw[h] if h < len(self._pv_fc.pv_kw) else 0.0
        if pv < 0.0:
            pv = 0.0
        if noise and "pv_failure" not in self._faults:
            rng = random.Random(self.seed * 7919 + 1 + int(hour * 100))
            if rng.random() < self.CLOUD_P:
                pv *= (1.0 - self.CLOUD_FACTOR) if rng.random() < 0.5 else (1.0 + self.CLOUD_FACTOR)
        if "pv_failure" in self._faults:
            pv = 0.0
        return max(0.0, pv)

    def _ambient_c(self, hour: float) -> float:
        h = int(round(hour)) % 24
        amb = self.weather.temp_c[h] if h < len(self.weather.temp_c) else 25.0
        if "overheat" in self._faults:
            amb += 20.0
        return float(amb)

    # ---------- 单步 ----------

    def step(self, hour: float, requested_kw: float, dt_hours: float = 1.0) -> SiteReading:
        hour = float(hour)
        dt = float(dt_hours) if dt_hours and dt_hours > 0 else 1.0
        state = self._state
        cfg = self.battery.cfg

        load_kw = self._hourly_load_kw(hour)
        pv_kw = self._hourly_pv_kw(hour)

        req = float(requested_kw) if _is_finite(requested_kw) else 0.0
        if "grid_outage" in self._faults:
            req = -load_kw  # 断电:仅由电池带载
        battery_kw = self.battery.feasible_power(state, req)

        selfheat = self.SELF_HEAT_K * abs(battery_kw) / max(1e-9, cfg.max_discharge_kw)
        if abs(battery_kw) < 1e-9:
            self._held_h = min(self.HOLD_HEAT_CAP_H, self._held_h + dt)
        else:
            self._held_h = 0.0
        temp_c = self._ambient_c(hour) + selfheat + self.HOLD_HEAT_K * self._held_h

        self._state, _deg = self.battery.step(state, battery_kw, dt, temp_c=temp_c)

        if "grid_outage" in self._faults:
            grid_kw = 0.0
        else:
            grid_kw = load_kw - pv_kw + battery_kw

        self._t += dt
        reading = SiteReading(
            ts=self._t, hour=hour, soc=self._state.soc, pv_kw=pv_kw,
            load_kw=load_kw, battery_kw=battery_kw, grid_kw=grid_kw,
            price=self.tariff.price_at(hour), tier=self.tariff.tier_at(hour),
            temp_c=temp_c)
        return reading

    def run_day(self, schedule: Optional[List[SchedulePoint]] = None) -> List[SiteReading]:
        readings: List[SiteReading] = []
        for i in range(24):
            kw = 0.0
            if schedule is not None and i < len(schedule):
                kw = float(schedule[i].battery_kw)
            readings.append(self.step(float(i), kw, dt_hours=1.0))
        return readings

    # ---------- 故障注入 ----------

    def inject_fault(self, kind: str) -> None:
        if kind not in ("pv_failure", "grid_outage", "overheat"):
            raise ValueError("unknown fault kind: %r" % (kind,))
        self._faults.add(kind)

    def clear_faults(self) -> None:
        self._faults.clear()

    @property
    def faults(self) -> Tuple[str, ...]:
        return tuple(sorted(self._faults))

    # ---------- 闭环 MPC ----------

    def run_closed_loop(self, tariff: TariffPlan, optimizer_factory, params: PolicyParams,
                        steps: int = 96, dt_hours: float = 0.25) -> Tuple[List[SiteReading], List[Dict[str, object]]]:
        """滚动重规划闭环:每小时重优化,执行当前小时的 setpoint 拆到 dt 子步。

        optimizer_factory(params) 必须返回带 optimize(load_kw, pv_kw, hours) 的优化器。
        以孪生真实 SOC 作为 soc_start 重新规划,展示预测与现实的发散 + 滚动纠偏。
        """
        readings: List[SiteReading] = []
        replan_events: List[Dict[str, object]] = []
        per_hour = max(1, int(round(1.0 / dt_hours)))
        setpoints: List[float] = [0.0] * per_hour

        for i in range(int(steps)):
            hour = i * dt_hours
            if i % per_hour == 0:
                h = int(hour)
                horizon = max(1, 24 - h)
                hours = [float(x) for x in range(h, h + horizon)]
                load_kw = [self._hourly_load_kw(x) for x in hours]
                pv_kw = [self._hourly_pv_kw(x, noise=False) for x in hours]
                self.battery.cfg.soc_start = self._state.soc
                optimizer = optimizer_factory(params)
                res = optimizer.optimize(load_kw, pv_kw, hours=hours, horizon_hours=horizon)
                plan_by_hour = {float(p.hour): p.battery_kw for p in res.points}
                setpoints = [float(plan_by_hour.get(h + j * dt_hours, 0.0))
                             for j in range(per_hour)]
                savings = float(res.savings_cny) if res.solver_status == "optimal" else 0.0
                replan_events.append({"step": i, "hour": h,
                                      "soc": round(self._state.soc, 4),
                                      "savings_forecast": round(savings, 4)})
            kw = setpoints[i % per_hour] if i % per_hour < len(setpoints) else 0.0
            readings.append(self.step(hour, kw, dt_hours=dt_hours))

        return readings, replan_events


def _is_finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False