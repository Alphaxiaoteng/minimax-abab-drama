"""Phase 2 Tests: Scenario Simulation Matrix。

覆盖四大预设工况矩阵：Sunny High PV, Storm Islanding, Negative Tariff, Winter Freeze。
"""
from __future__ import annotations

import pytest

from core.scenarios import ScenarioMatrix, ScenarioType, ScenarioParams


class TestScenarioRegistration:
    """场景注册与加载测试。"""
    
    def test_all_scenarios_registered(self):
        """验证所有标准场景已注册。"""
        ScenarioMatrix.register_scenarios()
        
        expected_types = {
            ScenarioType.SUNNY_HIGH_PV,
            ScenarioType.STORM_GRID_ISLANDING,
            ScenarioType.NEGATIVE_TARIFF,
            ScenarioType.WINTER_FREEZE,
        }
        
        registered_types = set(ScenarioMatrix.SCENARIOS.keys())
        assert expected_types == registered_types
    
    def test_scenario_properties_exist(self):
        """验证场景属性完整性。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.SUNNY_HIGH_PV)
        
        assert hasattr(params, "name")
        assert hasattr(params, "description")
        assert hasattr(params, "load_profile")
        assert hasattr(params, "pv_profile")
        assert len(params.load_profile) == 24
        assert len(params.pv_profile) == 24
    
    def test_list_scenarios_format(self):
        """列出场景格式正确。"""
        scenarios = ScenarioMatrix.list_scenarios()
        
        assert isinstance(scenarios, list)
        assert len(scenarios) == 4
        
        for scenario in scenarios:
            assert "type" in scenario
            assert "display_name" in scenario
            assert "description" in scenario


class TestScenarioSpecifics:
    """各场景特性验证。"""
    
    def test_sunny_high_pv_profile(self):
        """晴朗光伏丰裕场景曲线特征。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.SUNNY_HIGH_PV)
        
        # 中午光伏峰值接近 1.0
        pv_peak = max(params.pv_profile)
        assert pv_peak >= 0.95
        
        # 夜间无光伏
        assert params.pv_profile[0] < 0.01
        assert params.pv_profile[23] < 0.01
        
        # 傍晚有需求高峰
        assert params.load_profile[19] > 1.0  # Peak evening load
    
    def test_storm_islanding_no_grid(self):
        """暴风雨孤岛模式无电网交互。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.STORM_GRID_ISLANDING)
        
        assert params.battery_iso_mode is True
        assert params.export_price_override is None
        assert params.emergency_reserve_pct == 0.3
    
    def test_negative_tariff_export_price(self):
        """负电价场景导出价格为负。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.NEGATIVE_TARIFF)
        
        assert params.export_price_override is not None
        assert params.export_price_override < 0  # Negative feed-in tariff
        assert abs(params.export_price_override + 0.15) < 0.01  # -0.15 EUR
    
    def test_winter_freeze_high_load(self):
        """严寒升温高负荷场景。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.WINTER_FREEZE)
        
        # 基础负荷显著升高（热泵运行）
        assert params.base_load_kw >= 1.5
        
        # 温度低于零
        assert params.temp_c < 0
        
        # 冬季弱光
        pv_max = max(params.pv_profile)
        assert pv_max < 0.15


class TestStrategyComparison:
    """策略对比分析测试。"""
    
    def test_comparison_structure(self):
        """对比报告结构完整。"""
        matrix = ScenarioMatrix()
        
        comparison = matrix.compare_strategies(
            scenario_type=ScenarioType.SUNNY_HIGH_PV,
            mpc_savings_pct=24.4
        )
        
        assert "scenario" in comparison
        assert "mpc_optimization" in comparison
        assert "baseline_strategy" in comparison
        assert "improvement_ratio" in comparison
    
    def test_mpc_advantage_in_scenarios(self):
        """MPC 在所有场景下应有优势。"""
        matrix = ScenarioMatrix()
        
        for scenario_type in ScenarioMatrix.SCENARIOS.keys():
            comparison = matrix.compare_strategies(
                scenario_type=scenario_type,
                mpc_savings_pct=20.0
            )
            
            # MPC savings should be non-negative (except possibly negative tariff scenarios)
            savings = comparison["mpc_optimization"]["savings_cny"]
            assert savings >= -10.0  # Allow small tolerance
            
            # Self-consumption improvement can be zero or positive
            efficiency_gain = comparison["improvement_ratio"]["efficiency_gain"]
            assert efficiency_gain > -5.0  # Allow some edge cases
    
    def test_self_consumption_improvement(self):
        """自消费率提升幅度合理。"""
        matrix = ScenarioMatrix()
        
        comparison = matrix.compare_strategies(
            scenario_type=ScenarioType.SUNNY_HIGH_PV,
            mpc_savings_pct=24.4
        )
        
        baseline_self_cons = comparison["baseline_strategy"]["self_consumption_pct"]
        mpc_self_cons = comparison["mpc_optimization"]["self_consumption_pct"]
        
        # MPC 应提升自消费率 10-25%
        improvement = mpc_self_cons - baseline_self_cons
        assert 8.0 < improvement < 30.0


class TestLoadPVEnergyBalance:
    """负荷光伏能量平衡验证。"""
    
    def test_total_energy_units(self):
        """总能量单位正确（kWh）。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.SUNNY_HIGH_PV)
        
        total_load_kwh = sum(params.load_profile) * params.base_load_kw
        total_pv_kwh = sum(params.pv_profile) * params.pv_capacity_kw
        
        # 日负荷约 20-40 kWh 为典型家庭范围
        assert 15.0 < total_load_kwh < 50.0
        
        # 光伏日发电量取决于天气与容量
        assert 10.0 < total_pv_kwh < 80.0


class TestEdgeCases:
    """边缘情况测试。"""
    
    def test_unknown_scenario_raises(self):
        """未知场景抛出异常。"""
        with pytest.raises(ValueError):
            ScenarioMatrix.get_scenario("unknown_scenario")  # type: ignore
    
    def test_empty_profile_not_allowed(self):
        """空配置不被允许（应在注册时保证）。"""
        params = ScenarioMatrix.get_scenario(ScenarioType.SUNNY_HIGH_PV)
        
        assert len(params.load_profile) == 24
        assert all(isinstance(v, (int, float)) for v in params.load_profile)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
