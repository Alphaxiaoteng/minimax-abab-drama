# -*- coding: utf-8 -*-
"""
test_simulation.py
==================
测试套件：验证钠电池模型、AIDC 负载模型与优化求解器的物理合理性与计算正确性。
"""

import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.sodium_battery import SodiumBatterySystem, SodiumBatteryConfig
from src.models.aidc_workload import AIDCWorkloadGenerator, AIDCProfileConfig
from src.optimizer.peak_shaving_solver import MicrogridPeakShavingSolver
from src.main import run_aidc_simulation

class TestNaZhouAIDCSimulation(unittest.TestCase):
    def setUp(self):
        self.battery_config = SodiumBatteryConfig(
            nominal_capacity_kwh=1000.0,
            max_charge_power_kw=1000.0,
            max_discharge_power_kw=1000.0,
            initial_soc=0.5
        )
        self.bess = SodiumBatterySystem(self.battery_config)

    def test_battery_charge_discharge(self):
        """测试电池充放电能量守恒与 SOC 约束"""
        # 放电 500kW 持续 0.5 小时
        power, cost = self.bess.step(500.0, 0.5)
        self.assertAlmostEqual(power, 500.0, delta=1.0)
        self.assertLess(self.bess.current_soc, 0.5)
        self.assertGreater(cost, 0.0)

        # 充电 800kW 持续 0.5 小时
        prev_soc = self.bess.current_soc
        p_ch, _ = self.bess.step(-800.0, 0.5)
        self.assertLess(p_ch, 0.0)
        self.assertGreater(self.bess.current_soc, prev_soc)

    def test_aidc_workload_generation(self):
        """测试算力负载生成维度与 PUE 合理性"""
        gen = AIDCWorkloadGenerator()
        res = gen.generate_24h_profile(seed=123)
        self.assertEqual(len(res["hours"]), 96)
        self.assertTrue(np.all(res["dynamic_pue"] >= 1.05))
        self.assertTrue(np.all(res["dynamic_pue"] <= 1.40))
        self.assertTrue(np.all(res["facility_total_kw"] > res["it_power_kw"]))

    def test_solver_peak_reduction(self):
        """测试优化求解器削峰率与费用节省为正"""
        gen = AIDCWorkloadGenerator()
        profile = gen.generate_24h_profile(seed=42)
        tariff = gen.get_tou_tariff(profile["hours"])

        solver = MicrogridPeakShavingSolver(SodiumBatteryConfig(
            nominal_capacity_kwh=4000.0,
            max_charge_power_kw=2500.0,
            max_discharge_power_kw=4000.0
        ))
        result = solver.solve(profile["facility_total_kw"], profile["hours"], tariff)

        self.assertGreater(result.peak_reduction_kw, 0.0, "削峰功率必须大于 0")
        self.assertGreater(result.peak_reduction_percent, 4.0, "削峰率应显著 (>=4%)")
        self.assertGreater(result.net_savings, 0.0, "综合节约金额必须为正")

    def test_end_to_end_main(self):
        """测试端到端主程序执行与 SVG 产物生成"""
        test_docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
        summary = run_aidc_simulation(output_dir=test_docs_dir)
        self.assertIn("peak_reduction_kw", summary)
        self.assertTrue(os.path.exists(summary["chart_path"]))
        self.assertGreater(os.path.getsize(summary["chart_path"]), 1000)

if __name__ == "__main__":
    unittest.main()
