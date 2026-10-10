# -*- coding: utf-8 -*-
"""
peak_shaving_solver.py
======================
微电网削峰填谷与需量电费优化算法求解器 (Microgrid Peak-Shaving Optimizer)。
面向 AIDC 智算中心大算力瞬态冲击，结合分时电价 (TOU) 与最大需量电价 (Demand Charge)，
基于启发式动态规划与门限削峰法，计算 24 小时 96 步钠电池充放电最优策略。
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Any
from ..models.sodium_battery import SodiumBatterySystem, SodiumBatteryConfig

@dataclass
class OptimizationResult:
    time_hours: np.ndarray
    original_load_kw: np.ndarray
    grid_power_kw: np.ndarray
    battery_power_kw: np.ndarray
    battery_soc: np.ndarray
    tou_tariff: np.ndarray
    cost_without_bess: float
    cost_with_bess: float
    net_savings: float
    savings_percent: float
    peak_without_kw: float
    peak_with_kw: float
    peak_reduction_kw: float
    peak_reduction_percent: float
    battery_cycle_cost: float
    daily_throughput_kwh: float

class MicrogridPeakShavingSolver:
    def __init__(self, battery_config: SodiumBatteryConfig = None, demand_charge_rate_per_kw_month: float = 42.0):
        self.battery_config = battery_config or SodiumBatteryConfig()
        self.demand_charge_rate_per_kw_day = demand_charge_rate_per_kw_month / 30.0  # 折算每日需量电价

    def solve(
        self,
        facility_load_kw: np.ndarray,
        hours: np.ndarray,
        tou_tariff: np.ndarray,
        delta_hours: float = 0.25
    ) -> OptimizationResult:
        """
        求解 24 小时微电网功率分配最优解。
        :param facility_load_kw: 原始数据中心总负荷序列 (96步)
        :param hours: 时间刻度序列 (0.0 ~ 24.0)
        :param tou_tariff: 对应的分时电价序列 (元/kWh)
        :param delta_hours: 时间片步长 (0.25小时 = 15分钟)
        """
        T = len(facility_load_kw)
        battery = SodiumBatterySystem(self.battery_config)
        peak_no_bess = float(np.max(facility_load_kw))

        # 候选削峰门限 (从峰值的 70% 到 95%)
        best_net_savings = -float("inf")
        best_grid_power = np.copy(facility_load_kw)
        best_bat_power = np.zeros(T)
        best_soc = np.zeros(T)

        for target_peak_ratio in np.linspace(0.70, 0.95, 30):
            target_grid_peak = peak_no_bess * target_peak_ratio
            battery.reset()
            sim_grid = np.zeros(T)
            sim_bat = np.zeros(T)
            sim_soc = np.zeros(T)

            for t in range(T):
                load = facility_load_kw[t]
                tariff = tou_tariff[t]

                # 规则 1：硬性削峰防护 (Peak Shaving Hard Constraint)
                # 无论处于何种电价时段，只要负荷超出目标顶峰，优先放电削平
                if load > target_grid_peak:
                    needed_shave = load - target_grid_peak
                    actual_power, _ = battery.step(needed_shave, delta_hours)
                elif tariff >= 1.15 and battery.current_soc > 0.20:
                    # 规则 2：尖峰/高峰期电价套利放电 (Arbitrage Discharge)
                    arbitrage_discharge = min(
                        self.battery_config.max_discharge_power_kw * 0.6,
                        load  # 避免电网倒送
                    )
                    actual_power, _ = battery.step(arbitrage_discharge, delta_hours)
                elif tariff <= 0.40 and (load + 500.0) < target_grid_peak:
                    # 规则 3：低谷期且负荷有富余时充电 (Valley Charging)
                    available_headroom = max(0.0, target_grid_peak - load)
                    charge_power = min(self.battery_config.max_charge_power_kw, available_headroom)
                    actual_power, _ = battery.step(-charge_power, delta_hours)
                else:
                    # 规则 4：平段待机保持
                    actual_power, _ = battery.step(0.0, delta_hours)

                sim_bat[t] = actual_power
                sim_grid[t] = load - actual_power
                sim_soc[t] = battery.current_soc

            # 评估经济收益
            energy_cost = np.sum(sim_grid * tou_tariff * delta_hours)
            peak_grid = float(np.max(sim_grid))
            demand_cost = peak_grid * self.demand_charge_rate_per_kw_day
            throughput = np.sum(np.abs(sim_bat)) * delta_hours
            deg_cost = throughput * self.battery_config.cycle_degradation_cost_per_kwh
            total_cost = energy_cost + demand_cost + deg_cost

            # 无储能对比
            base_energy = np.sum(facility_load_kw * tou_tariff * delta_hours)
            base_demand = peak_no_bess * self.demand_charge_rate_per_kw_day
            base_cost = base_energy + base_demand
            net_savings = base_cost - total_cost

            # 选取净收益最大且削峰确实生效的最佳方案
            if net_savings > best_net_savings and (peak_no_bess - peak_grid) > 50.0:
                best_net_savings = net_savings
                best_grid_power = sim_grid
                best_bat_power = sim_bat
                best_soc = sim_soc

        # 兜底：如果遍历未选出更佳方案，执行基准削峰
        if best_net_savings == -float("inf"):
            battery.reset()
            fallback_target = peak_no_bess * 0.88
            for t in range(T):
                load = facility_load_kw[t]
                if load > fallback_target:
                    actual_power, _ = battery.step(load - fallback_target, delta_hours)
                else:
                    actual_power, _ = battery.step(0.0, delta_hours)
                best_bat_power[t] = actual_power
                best_grid_power[t] = load - actual_power
                best_soc[t] = battery.current_soc

        # 统计最终结果
        energy_cost_no_bess = np.sum(facility_load_kw * tou_tariff * delta_hours)
        demand_cost_no_bess = peak_no_bess * self.demand_charge_rate_per_kw_day
        total_cost_no_bess = energy_cost_no_bess + demand_cost_no_bess

        energy_cost_with_bess = np.sum(best_grid_power * tou_tariff * delta_hours)
        peak_with_bess = float(np.max(best_grid_power))
        demand_cost_with_bess = peak_with_bess * self.demand_charge_rate_per_kw_day
        throughput = np.sum(np.abs(best_bat_power)) * delta_hours
        battery_cycle_cost = throughput * self.battery_config.cycle_degradation_cost_per_kwh
        total_cost_with_bess = energy_cost_with_bess + demand_cost_with_bess + battery_cycle_cost

        net_savings = total_cost_no_bess - total_cost_with_bess
        savings_percent = (net_savings / total_cost_no_bess) * 100.0

        peak_reduction = peak_no_bess - peak_with_bess
        peak_reduction_percent = (peak_reduction / peak_no_bess) * 100.0

        return OptimizationResult(
            time_hours=hours,
            original_load_kw=facility_load_kw,
            grid_power_kw=best_grid_power,
            battery_power_kw=best_bat_power,
            battery_soc=best_soc,
            tou_tariff=tou_tariff,
            cost_without_bess=total_cost_no_bess,
            cost_with_bess=total_cost_with_bess,
            net_savings=net_savings,
            savings_percent=savings_percent,
            peak_without_kw=peak_no_bess,
            peak_with_kw=peak_with_bess,
            peak_reduction_kw=peak_reduction,
            peak_reduction_percent=peak_reduction_percent,
            battery_cycle_cost=battery_cycle_cost,
            daily_throughput_kwh=throughput
        )
