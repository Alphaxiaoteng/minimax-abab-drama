"""电池模型:SOC 积分、退化成本线性化、温度降额。

power_kw 为电网侧/交流侧功率;充电时电池吸收 power_kw*sqrt(rte),
放电时电池释放 |power_kw|*sqrt(rte) 到交流侧。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Tuple


@dataclass
class BatteryConfig:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    round_trip_eff: float = 0.90
    soc_min: float = 0.05
    soc_max: float = 1.0
    soc_start: float = 0.30
    cycle_life: int = 6000
    pack_cost_cny: float = 12000.0
    reserve_soc: float = 0.10


@dataclass
class BatteryState:
    soc: float
    soh: float = 1.0
    cycles: float = 0.0
    temp_c: float = 25.0


class BatteryModel:
    def __init__(self, cfg: BatteryConfig) -> None:
        self.cfg = cfg
        self._sqrt_rte = math.sqrt(cfg.round_trip_eff)

    def degradation_cost(self, throughput_kwh: float) -> float:
        """线性化每 kWh 吞吐资本成本。

        公式: throughput_kwh * pack_cost_cny / (cycle_life * 2 * capacity_kwh)
        含义:电池全寿命可吞吐 cycle_life*2*capacity kWh;每吞吐 1 kWh
        分摊 pack_cost_cny / 总吞吐 的资本折旧。
        """
        total_throughput = self.cfg.cycle_life * 2.0 * self.cfg.capacity_kwh
        return throughput_kwh * self.cfg.pack_cost_cny / total_throughput

    def _temp_derate(self, temp_c: float) -> float:
        """温度 > 45°C 线性降额至 60°C 时 50%,下限 0.5。"""
        if temp_c <= 45.0:
            return 1.0
        ratio = (temp_c - 45.0) / 15.0
        return max(0.5, 1.0 - 0.5 * ratio)

    def feasible_power(self, state: BatteryState, power_kw: float, temp_c: Optional[float] = None) -> float:
        """夹紧 power_kw 到 SOC 与功率边界内的可行值。"""
        derate = self._temp_derate(temp_c if temp_c is not None else state.temp_c)
        max_charge = self.cfg.max_charge_kw * derate
        max_discharge = self.cfg.max_discharge_kw * derate

        if power_kw > 0:
            headroom = (self.cfg.soc_max - state.soc) * self.cfg.capacity_kwh / self._sqrt_rte
            return min(power_kw, max_charge, max(0.0, headroom))
        elif power_kw < 0:
            available = (state.soc - self.cfg.soc_min) * self.cfg.capacity_kwh * self._sqrt_rte
            return max(power_kw, -max_discharge, -max(0.0, available))
        return 0.0

    def step(self, state: BatteryState, power_kw: float, hours: float,
             temp_c: Optional[float] = None) -> Tuple[BatteryState, float]:
        """一步积分。返回 (新状态, 退化成本元)。不修改入参。"""
        effective_temp = temp_c if temp_c is not None else state.temp_c
        clamped = self.feasible_power(state, power_kw, effective_temp)
        if clamped == 0.0:
            new_state = replace(state, temp_c=effective_temp)
            return new_state, 0.0

        # §3.7 递推系数: charge 抬升 soc=sqrt(rte)/C, discharge 压低 soc=1/(sqrt(rte)*C)
        # 即每 1 AC kWh 放电需从电池取出 1/sqrt(rte) kWh, 往返损耗 rte=(sqrt)^2 才成立。
        if clamped > 0:
            battery_kwh = clamped * hours * self._sqrt_rte
        else:
            battery_kwh = clamped * hours / self._sqrt_rte
        new_soc = state.soc + battery_kwh / self.cfg.capacity_kwh
        new_soc = max(self.cfg.soc_min, min(self.cfg.soc_max, new_soc))

        throughput = abs(clamped) * hours
        new_cycles = state.cycles + throughput / (2.0 * self.cfg.capacity_kwh)

        deg_cost = self.degradation_cost(throughput)
        new_state = BatteryState(soc=new_soc, soh=state.soh, cycles=new_cycles, temp_c=effective_temp)
        return new_state, deg_cost