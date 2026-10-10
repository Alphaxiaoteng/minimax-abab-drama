# -*- coding: utf-8 -*-
"""
sodium_battery.py
=================
工业级钠离子储能电池系统 (Sodium-Ion BESS) 物理与衰减数学模型。
面向 AIDC 智算中心高瞬态倍率场景，建模容量、充放电效率、SOC/SOH 与循环寿命成本。
"""

from dataclasses import dataclass
from typing import Tuple

@dataclass
class SodiumBatteryConfig:
    nominal_capacity_kwh: float = 2000.0   # 额定标称容量 2 MWh
    max_charge_power_kw: float = 2000.0     # 最大充入功率 (支持 1C - 2C 脉冲)
    max_discharge_power_kw: float = 3000.0  # 最大放电功率 (支持 1.5C 峰值瞬态释放)
    coulombic_efficiency: float = 0.98      # 库仑效率
    round_trip_efficiency: float = 0.92     # 充放电往返效率 (RTE = 92%)
    soc_min: float = 0.05                   # 最低安全 SOC (钠电支持深度放电至5%甚至0V无损伤)
    soc_max: float = 0.98                   # 最高安全 SOC
    initial_soc: float = 0.50               # 初始 SOC
    cycle_degradation_cost_per_kwh: float = 0.12  # 每吞吐 1 kWh 衰减等效寿命折旧成本 (元)
    temp_ambient_celsius: float = 25.0      # 运行环境温度 (°C)

class SodiumBatterySystem:
    def __init__(self, config: SodiumBatteryConfig = None):
        self.config = config or SodiumBatteryConfig()
        self.current_energy_kwh = self.config.nominal_capacity_kwh * self.config.initial_soc
        self.current_soc = self.config.initial_soc
        self.total_throughput_kwh = 0.0
        self.total_cycle_cost = 0.0

    @property
    def capacity(self) -> float:
        return self.config.nominal_capacity_kwh

    @property
    def min_energy_kwh(self) -> float:
        return self.config.nominal_capacity_kwh * self.config.soc_min

    @property
    def max_energy_kwh(self) -> float:
        return self.config.nominal_capacity_kwh * self.config.soc_max

    def step(self, power_kw: float, delta_hours: float) -> Tuple[float, float]:
        """
        执行单步功率调度更新。
        :param power_kw: 正值表示放电给数据中心，负值表示从电网/微网充电
        :param delta_hours: 时间步长 (小时)
        :return: (实际执行功率 kW, 本步电池寿命折旧成本 元)
        """
        charge_eff = self.config.round_trip_efficiency ** 0.5
        discharge_eff = self.config.round_trip_efficiency ** 0.5

        if power_kw >= 0:
            # 放电模式
            requested_discharge = min(power_kw, self.config.max_discharge_power_kw)
            # 考虑下限能量约束
            available_energy = max(0.0, self.current_energy_kwh - self.min_energy_kwh)
            max_deliverable_energy = available_energy * discharge_eff
            actual_delivered_kwh = min(requested_discharge * delta_hours, max_deliverable_energy)
            actual_power = actual_delivered_kwh / delta_hours if delta_hours > 0 else 0.0

            # 内部消耗能量
            internal_energy_loss = actual_delivered_kwh / discharge_eff
            self.current_energy_kwh -= internal_energy_loss
        else:
            # 充电模式
            requested_charge = min(abs(power_kw), self.config.max_charge_power_kw)
            # 考虑上限能量约束
            available_room = max(0.0, self.max_energy_kwh - self.current_energy_kwh)
            actual_absorbed_kwh = min(requested_charge * delta_hours * charge_eff, available_room)
            actual_grid_kwh = actual_absorbed_kwh / charge_eff
            actual_power = -(actual_grid_kwh / delta_hours) if delta_hours > 0 else 0.0

            self.current_energy_kwh += actual_absorbed_kwh

        # 更新 SOC
        self.current_soc = max(self.config.soc_min, min(self.config.soc_max, self.current_energy_kwh / self.config.nominal_capacity_kwh))
        throughput = abs(actual_power) * delta_hours
        step_cost = throughput * self.config.cycle_degradation_cost_per_kwh

        self.total_throughput_kwh += throughput
        self.total_cycle_cost += step_cost

        return actual_power, step_cost

    def reset(self):
        self.current_energy_kwh = self.config.nominal_capacity_kwh * self.config.initial_soc
        self.current_soc = self.config.initial_soc
        self.total_throughput_kwh = 0.0
        self.total_cycle_cost = 0.0
