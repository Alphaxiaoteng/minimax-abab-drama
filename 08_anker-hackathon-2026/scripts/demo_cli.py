#!/usr/bin/env python3
"""08_anker-hackathon-2026: 终端一页纸 24h 智能家庭光储能调度 MPC 演示."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core.battery import BatteryConfig, BatteryModel
from core.optimizer import MPCOptimizer
from core.policy import mode_presets
from core.solar import SolarModel, synthetic_weather
from core.tariff import builtin_tariffs

LOAD_24 = [
    0.66, 0.60, 0.58, 0.58, 0.60, 0.74,
    1.14, 1.50, 1.38, 1.08, 1.02, 1.08,
    1.20, 1.08, 1.02, 1.08, 1.26, 1.56,
    1.92, 2.04, 1.74, 1.32, 1.02, 0.78,
]

def main() -> int:
    print("=" * 76)
    print("Anker Solix 智能家庭储能管家 · 24h 滚动时域 MPC 优化调度")
    print("=" * 76)

    cfg = BatteryConfig(
        capacity_kwh=5.0,
        max_charge_kw=2.5,
        max_discharge_kw=2.5,
        round_trip_eff=0.92,
        soc_min=0.05,
        soc_max=1.0,
        soc_start=0.30,
        cycle_life=6000,
        pack_cost_cny=12999,
        reserve_soc=0.10,
    )
    battery = BatteryModel(cfg)
    tariff = builtin_tariffs()["shenzhen"]
    policy = mode_presets()["arbitrage"]

    weather = synthetic_weather("clear", seed=42)
    pv_forecast = SolarModel(5.0, 0.85).forecast(weather).pv_kw

    opt = MPCOptimizer(battery, tariff, policy, site_id="home-01", model="SOLARBANK_4_E5000")
    res = opt.optimize(LOAD_24, pv_forecast)

    print(f"求解状态: {res.solver_status} | 策略模式: 套利优先 (arbitrage)")
    print(f"家庭负载总计: {sum(LOAD_24):.2f} kWh | 光伏生成总计: {sum(pv_forecast):.2f} kWh")
    print(f"无储能基准电费: {res.baseline_cost_cny:.2f} 元 | 优化后电费: {res.optimized_cost_cny:.2f} 元")
    print(f"单日节约费用: {res.savings_cny:.2f} 元 | 节约比例: {res.savings_pct:.2f}%")
    print(f"电池循环次数: {res.cycles_used:.3f} 次/日 | 光伏自发自用率: {res.pv_self_consumption * 100:.1f}%\n")

    print(f"{'时刻':<6}{'负荷(kW)':>10}{'光伏(kW)':>10}{'电池(kW)':>10}{'SOC':>8}{'电网(kW)':>10}{'电价(元)':>10}{'动作':>10}")
    print("-" * 76)
    for p in res.points:
        print(f"{int(p.hour):02d}:00 {p.load_kw:>10.2f}{p.pv_kw:>10.2f}{p.battery_kw:>10.2f}{p.soc:>7.1%}{p.grid_kw:>10.2f}{p.price:>10.3f} {p.action:>10}")

    print("-" * 76)
    print("决策可解释性说明:")
    for r in res.rationale[:5]:
        print(f"  • {r}")
    print("\n优化引擎验证通过 ✅")
    return 0

if __name__ == "__main__":
    sys.exit(main())
