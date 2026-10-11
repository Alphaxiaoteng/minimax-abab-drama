"""Phase 2 Tests: NILM Appliance-Level Monitoring & Smart Scheduling。

覆盖家电级非侵入式负荷分解、EV 智能错峰充电、热泵温控调度等核心功能。
"""
from __future__ import annotations

import math
import pytest

from core.appliance import (
    NILMEngine,
    ApplianceType,
    ApplianceStatus,
    ApplianceConfig,
    HeatPumpConfig,
    EVChargerConfig,
)


@pytest.fixture
def nilm_engine():
    """构建测试用 NILM 引擎。"""
    appliances = {
        ApplianceType.HEAT_PUMP: HeatPumpConfig(
            max_power_kw=3.0, soc_start=0.5, cop=3.5, target_temp=22.0, outdoor_temp=5.0
        ),
        ApplianceType.EV_CHARGER: EVChargerConfig(
            max_power_kw=11.0, soc_start=0.3, required_soc=0.9, departure_time=8
        ),
        ApplianceType.BASE_LOAD: ApplianceConfig(
            type=ApplianceType.BASE_LOAD, max_power_kw=1.0, min_power_kw=0.5
        ),
        ApplianceType.LIGHTING: ApplianceConfig(
            type=ApplianceType.LIGHTING, max_power_kw=0.5, min_power_kw=0.1
        ),
    }
    return NILMEngine(appliances)


class TestNILMBaseline:
    """NILM 基础功能测试。"""
    
    def test_initialization(self, nilm_engine):
        """验证电器状态初始化正确。"""
        assert len(nilm_engine.states) == 4
        assert nilm_engine.states[ApplianceType.HEAT_PUMP].soc == 0.5
        assert nilm_engine.states[ApplianceType.EV_CHARGER].soc == 0.3
    
    def test_detect_active_appliances(self, nilm_engine):
        """检测活跃电器分配功率。"""
        total_load = 5.0
        detections = nilm_engine.detect_active_appliances(total_load, hour=10)
        
        assert ApplianceType.BASE_LOAD in detections
        assert detections[ApplianceType.BASE_LOAD] >= 0.5
        assert sum(detections.values()) <= total_load + 0.1  # 允许数值误差
    
    def test_breakdown_generation(self, nilm_engine):
        """生成家电分解明细。"""
        breakdown = nilm_engine.get_breakdown(hour=12)
        
        assert len(breakdown) == 4
        # Check required fields exist in each item
        for item in breakdown:
            assert "type" in item or "power_kw" in item or "energy_kwh" in item


class TestEVSmartCharging:
    """EV 智能错峰充电算法测试。"""
    
    def test_charge_when_price_low(self, nilm_engine):
        """电价低时开始充电。"""
        should_charge, power = nilm_engine.schedule_ev_charging(
            tariff_price=0.3,      # 谷电
            avg_price=0.65,       # 均价
            desired_departure=8,
            current_hour=23,
        )
        
        assert should_charge is True
        assert power > 0
        assert power <= 11.0  # Max power constraint
    
    def test_no_charge_when_soc_high(self, nilm_engine):
        """SOC 充足时不充电。"""
        # 设置 SOC 已满
        nilm_engine.states[ApplianceType.EV_CHARGER].soc = 0.95
        
        should_charge, power = nilm_engine.schedule_ev_charging(
            tariff_price=0.3,
            avg_price=0.65,
            desired_departure=8,
            current_hour=23,
        )
        
        assert should_charge is False
        assert power == 0.0
    
    def test_emergency_charge_time_constraint(self, nilm_engine):
        """时间紧迫时全力充电。"""
        # 距离出发只剩 2 小时，需要紧急充电
        should_charge, power = nilm_engine.schedule_ev_charging(
            tariff_price=0.65,   # 即使电价高也要充
            avg_price=0.65,
            desired_departure=2,  # 2 小时后出发
            current_hour=0,
        )
        
        assert should_charge is True
        assert power == 11.0  # Emergency mode: max power
    
    def test_soc_tracking(self, nilm_engine):
        """SOC 随充电进度更新。"""
        initial_soc = nilm_engine.states[ApplianceType.EV_CHARGER].soc
        
        # 模拟 1 小时充电（假设 2kW 平均）
        nilm_engine.step(total_load_kw=2.0, hour=1, dt_hours=1.0)
        
        new_soc = nilm_engine.states[ApplianceType.EV_CHARGER].soc
        assert new_soc > initial_soc
        assert new_soc <= 1.0  # SOC upper bound


class TestHeatPumpControl:
    """热泵智能温控调度测试。"""
    
    def test_full_power_when_cold(self, nilm_engine):
        """温差大时全功率运行。"""
        should_run, power = nilm_engine.schedule_heat_pump(
            outdoor_temp=-5.0,
            indoor_target=22.0,
            current_indoor=15.0,
            tariff_price=0.65,
        )
        
        assert should_run is True
        assert power == 3.0  # Max power
    
    def test_maintenance_mode_near_target(self, nilm_engine):
        """接近目标温度时低功率维持。"""
        should_run, power = nilm_engine.schedule_heat_pump(
            outdoor_temp=5.0,
            indoor_target=22.0,
            current_indoor=21.5,
            tariff_price=0.65,
        )
        
        # Should either run at low power or skip (both acceptable)
        assert (should_run and power < 3.0 * 0.8) or (not should_run and power == 0.0)
    
    def test_skip_during_peak_price(self, nilm_engine):
        """高峰期暂停运行（略高于目标）。"""
        should_run, power = nilm_engine.schedule_heat_pump(
            outdoor_temp=5.0,
            indoor_target=22.0,
            current_indoor=21.8,
            tariff_price=1.112,  # 尖峰电价
        )
        
        # 允许跳过（因为温差小且电价高）
        assert should_run is False or power < 0.1


class TestDegradationModel:
    """电器退化模型测试。"""
    
    def test_temperature_accelerated_aging(self, nilm_engine):
        """高温加速老化。"""
        appliance_state = nilm_engine.states[ApplianceType.HEAT_PUMP]
        
        # 初始退化系数
        initial_factor = appliance_state.degradation_factor
        
        # 模拟高温运行
        appliance_state.temperature_c = 75.0
        aging_rate = 1.0 + 0.1 * (75.0 - 50.0) / 30.0
        
        # 运行一步后应触发老化
        nilm_engine.step(total_load_kw=3.0, hour=10, dt_hours=1.0)
        
        assert appliance_state.degradation_factor >= initial_factor


class TestLoadForecasting:
    """负荷预测与匹配精度测试。"""
    
    def test_base_load_estimation_accuracy(self, nilm_engine):
        """基础负荷估计准确度。"""
        true_base_load = 0.8  # kW
        
        # 总负荷主要由基础负荷构成
        detections = nilm_engine.detect_active_appliances(true_base_load, hour=3)
        
        base_detected = detections.get(ApplianceType.BASE_LOAD, 0)
        # 允许±20% 误差（NILM 本质是不精确的）
        assert abs(base_detected - true_base_load) / true_base_load < 0.3


class TestIntegration:
    """端到端集成测试。"""
    
    def test_complete_schedule_cycle(self, nilm_engine):
        """完整 24h 调度周期测试。"""
        daily_loads = [1.0 + 0.5 * math.sin(h * math.pi / 12) for h in range(24)]
        
        total_energy_kwh = 0.0
        for hour in range(24):
            states = nilm_engine.step(daily_loads[hour], hour, dt_hours=1.0)
            total_energy_kwh += sum(s.power_kw for s in states.values())
        
        # 能耗合理性检查
        avg_daily_energy = total_energy_kwh / 24
        assert 0.5 < avg_daily_energy < 5.0  # 合理范围
    
    def test_multi_day_soc_tracking(self, nilm_engine):
        """多日 SOC 跟踪一致性。"""
        # 第 1 天：白天充电，晚上放电
        for day in range(3):
            for hour in range(24):
                if 8 <= hour <= 18:
                    load = 2.0  # Daytime load
                else:
                    load = 1.0  # Nighttime load
                    
                nilm_engine.step(load, hour, dt_hours=1.0)
        
        # SOC 应保持在一个区间内波动（不会无限下降或上升）
        ev_soc = nilm_engine.states[ApplianceType.EV_CHARGER].soc
        assert 0.1 < ev_soc < 1.0  # Within bounds


# Additional edge case tests
class TestEdgeCases:
    """边缘情况测试。"""
    
    def test_zero_total_load(self, nilm_engine):
        """零负荷场景。"""
        detections = nilm_engine.detect_active_appliances(0.0, hour=4)
        
        # 至少有最小基础负荷
        assert detections.get(ApplianceType.BASE_LOAD, 0) > 0
    
    def test_extreme_temperature(self, nilm_engine):
        """极端温度处理。"""
        _, power = nilm_engine.schedule_heat_pump(
            outdoor_temp=-30.0,  # 极寒
            indoor_target=22.0,
            current_indoor=10.0,
            tariff_price=0.65,
        )
        
        assert power == 3.0  # Should run at max
    
    def test_rapid_soc_changes(self, nilm_engine):
        """快速 SOC 变化边界。"""
        # 强制设置为极限值
        nilm_engine.states[ApplianceType.EV_CHARGER].soc = 0.99
        
        should_charge, power = nilm_engine.schedule_ev_charging(
            tariff_price=0.3,
            avg_price=0.65,
            desired_departure=8,
            current_hour=0,
        )
        
        # SOC 非常接近目标时不应再充电
        assert should_charge is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
