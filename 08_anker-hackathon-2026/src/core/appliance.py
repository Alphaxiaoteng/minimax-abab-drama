"""家电级负荷分解与智能调度 (Appliance-Level NILM & Smart Scheduling)。

对标特斯拉 Powerwall 3 的电器分项监测：
- Heat Pump (热泵): 3kW，可调度，温度敏感
- EV Wallbox (充电桩): 11kW，柔性窗口，优先级控制
- Base Load (基础负荷): 不可控，随机波动
- Lighting/Socket (照明插座): 1kW，用户习惯模型

特征工程：
1. 非侵入式分解：基于总负荷曲线 + 已知电器功率谱匹配
2. 智能错峰充电：电价信号 + 电池 SOC + 用户行程需求
3. DoD/温度退化感知：深度放电与高温加速老化惩罚
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel


class ApplianceType(Enum):
    HEAT_PUMP = "heat_pump"       # 热泵 HVAC
    EV_CHARGER = "ev_charger"     # 电动汽车充电桩
    BASE_LOAD = "base_load"       # 基础家庭负荷
    LIGHTING = "lighting"         # 照明插座
    DISHWASHER = "dishwasher"     # 洗碗机（可选）
    WATER_HEATER = "water_heater"  # 电热水器（可选）


class ApplianceStatus(Enum):
    OFF = "off"
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    RUNNING = "running"
    DEFERRABLE = "deferrable"      # 可延迟
    
    
@dataclass
class ApplianceConfig:
    """电器配置参数。"""
    type: ApplianceType
    max_power_kw: float           # 最大功率 kW
    min_power_kw: float = 0.0     # 最小功率（阶梯控制）
    efficiency: float = 1.0       # 能效比
    soc_min: float = 0.0          # 最低电量/SOC（EV/储能专用）
    soc_max: float = 1.0          # 最高电量/SOC
    soc_start: float = 0.5        # 初始 SOC
    reserve_soc: float = 0.2      # 保留 SOC（应急容量）
    priority: int = 5             # 优先级 1-10，10 最高
    temp_sensitive: bool = False  # 温度敏感性（热泵）
    cold_start_cost: float = 0.0  # 冷启动额外成本（元）
    cycle_life: int = 3000        # 循环寿命
    cost_cny: float = 5000.0      # 设备成本（元）
    can_defer: bool = True        # 是否可推迟运行
    defer_max_hours: int = 12     # 最大推迟时长（小时）
    
    def __post_init__(self):
        if self.type in [ApplianceType.HEAT_PUMP, ApplianceType.EV_CHARGER]:
            assert 0.0 <= self.soc_min < self.soc_max <= 1.0


@dataclass 
class ApplianceState:
    """电器运行时状态。"""
    soc: float                     # 当前 SOC/电量百分比
    power_kw: float                # 实时功率（正=消耗，负=生产）
    energy_kwh: float              # 累计能耗
    status: ApplianceStatus = ApplianceStatus.OFF
    runtime_hours: float = 0.0     # 累计运行时间
    temperature_c: float = 25.0    # 设备温度
    degradation_factor: float = 1.0 # 退化系数（1.0=新，>1.0=老化加速）
    
    def to_dict(self) -> dict:
        return {
            "soc": round(self.soc, 4),
            "power_kw": round(self.power_kw, 4),
            "energy_kwh": round(self.energy_kwh, 4),
            "status": self.status.value,
            "runtime_hours": round(self.runtime_hours, 2),
            "temperature_c": round(self.temperature_c, 2),
            "degradation_factor": round(self.degradation_factor, 3),
        }


@dataclass
class HeatPumpConfig(ApplianceConfig):
    """热泵专用配置。"""
    type: ApplianceType = ApplianceType.HEAT_PUMP
    max_power_kw: float = 3.0
    cop: float = 3.5                # 制热 COP（能量输出/电能输入）
    target_temp: float = 22.0       # 目标室温
    outdoor_temp: float = 5.0       # 室外温度
    building_insulation: float = 0.5 # 建筑保温系数
    
    def __post_init__(self):
        super().__post_init__()
        

@dataclass
class EVChargerConfig(ApplianceConfig):
    """电动车充电桩配置。"""
    type: ApplianceType = ApplianceType.EV_CHARGER
    max_power_kw: float = 11.0
    departure_time: int = 8         # 出发时间（小时）
    required_soc: float = 0.9       # 所需 SOC
    charging_curve: str = "linear"  # 充电曲线：linear/sigmoid/steps
    
    def __post_init__(self):
        super().__post_init__()


class NILMEngine:
    """非侵入式负荷分解引擎。
    
    基于功率谱匹配的 NILM 算法：
    1. 采集总负荷曲线
    2. 基于已知电器功率指纹识别活跃设备
    3. 分解各电器能耗贡献
    """
    
    def __init__(self, appliances: Dict[ApplianceType, ApplianceConfig]):
        self.appliances = appliances
        self.states: Dict[ApplianceType, ApplianceState] = {}
        for atype, cfg in appliances.items():
            self.states[atype] = ApplianceState(
                soc=cfg.soc_start,
                power_kw=0.0,
                energy_kwh=0.0,
                status=ApplianceStatus.OFF,
            )
        
    def detect_active_appliances(self, total_load_kw: float, hour: int) -> Dict[ApplianceType, float]:
        """检测当前活跃电器及功率分配。
        
        Args:
            total_load_kw: 总负荷（kW）
            hour: 当前小时
            
        Returns:
            {ApplianceType: detected_power_kw}
        """
        detections: Dict[ApplianceType, float] = {}
        remaining = total_load_kw
        
        # 1. 首先匹配固定负载（基础负荷 + 照明）
        for atype in [ApplianceType.BASE_LOAD, ApplianceType.LIGHTING]:
            if atype in self.appliances:
                cfg = self.appliances[atype]
                base_power = cfg.min_power_kw + (cfg.max_power_kw - cfg.min_power_kw) * 0.5
                detections[atype] = base_power
                remaining -= base_power
        
        # 2. 匹配可调度电器（根据电价和 SOC）
        for atype in [ApplianceType.HEAT_PUMP, ApplianceType.EV_CHARGER]:
            if atype not in self.appliances:
                continue
                
            cfg = self.appliances[atype]
            state = self.states[atype]
            
            # 电价低于平均且 SOC 充足时开启
            if state.soc < cfg.soc_max and remaining > cfg.min_power_kw:
                power = min(cfg.max_power_kw, remaining, cfg.soc_max - state.soc * cfg.max_power_kw / 10)
                if power > cfg.min_power_kw:
                    detections[atype] = power
                    state.status = ApplianceStatus.CHARGING if atype == ApplianceType.EV_CHARGER else ApplianceStatus.RUNNING
                    remaining -= power
        
        # 剩余归入基础负荷（不确定性）
        if remaining > 0:
            if ApplianceType.BASE_LOAD in detections:
                detections[ApplianceType.BASE_LOAD] += remaining
            else:
                detections[ApplianceType.BASE_LOAD] = remaining
                
        return detections
    
    def schedule_ev_charging(self, tariff_price: float, avg_price: float, 
                            desired_departure: int, current_hour: int) -> Tuple[bool, float]:
        """智能 EV 错峰充电调度。
        
        Args:
            tariff_price: 当前电价
            avg_price: 日均价
            desired_departure: 期望出发时间
            current_hour: 当前小时
            
        Returns:
            (should_charge, recommended_power_kw)
        """
        cfg = self.appliances[ApplianceType.EV_CHARGER]
        state = self.states[ApplianceType.EV_CHARGER]
        
        # 条件 1: 需要充电（SOC 不足）
        if state.soc >= cfg.required_soc:
            return False, 0.0
            
        # 条件 2: 有足够时间充到目标
        hours_remaining = desired_departure - current_hour
        if hours_remaining <= 0:
            hours_remaining = 24 + desired_departure - current_hour
            
        required_energy = (cfg.required_soc - state.soc) * cfg.max_power_kw * 10  # kWh
        max_chargeable = hours_remaining * cfg.max_power_kw * 0.9  # 90% 效率
        
        if required_energy > max_chargeable:
            # 紧急模式：全力充电
            return True, cfg.max_power_kw
            
        # 条件 3: 电价低于均价时充电
        if tariff_price < avg_price * 0.8:  # 低于均价 20%
            charge_power = min(required_energy / max(hours_remaining, 1), cfg.max_power_kw)
            return True, charge_power
            
        return False, 0.0
    
    def schedule_heat_pump(self, outdoor_temp: float, indoor_target: float,
                          current_indoor: float, tariff_price: float) -> Tuple[bool, float]:
        """热泵智能温控调度。
        
        Args:
            outdoor_temp: 室外温度
            indoor_target: 目标室内温度
            current_indoor: 当前室内温度
            tariff_price: 当前电价
            
        Returns:
            (should_run, recommended_power_kw)
        """
        cfg = self.appliances[ApplianceType.HEAT_PUMP]
        state = self.states[ApplianceType.HEAT_PUMP]
        
        # 温度温差判断
        temp_diff = indoor_target - current_indoor
        if temp_diff > 2.0:  # 温差大，优先升温
            return True, cfg.max_power_kw
            
        if temp_diff < 0.5:  # 接近目标，低功率维持
            return True, cfg.min_power_kw * 0.5
            
        if temp_diff > 0:  # 略低于目标，间歇运行
            if tariff_price < 0.5:  # 谷电时段
                return True, cfg.max_power_kw * 0.7
            return False, 0.0
            
        return False, 0.0
    
    def step(self, total_load_kw: float, hour: int, dt_hours: float = 1.0) -> Dict[ApplianceType, ApplianceState]:
        """执行一步电器状态更新。
        
        Args:
            total_load_kw: 该时刻总负荷
            hour: 小时索引
            dt_hours: 时间步长
            
        Returns:
            {ApplianceType: updated_state}
        """
        detections = self.detect_active_appliances(total_load_kw, hour)
        
        for atype, power_detected in detections.items():
            cfg = self.appliances[atype]
            state = self.states[atype]
            
            # 更新功率与能耗
            state.power_kw = power_detected
            state.energy_kwh += power_detected * dt_hours
            state.runtime_hours += dt_hours
            
            # 更新 SOC（仅 EV）
            if atype == ApplianceType.EV_CHARGER and power_detected > 0:
                state.soc = min(1.0, state.soc + power_detected * dt_hours / (cfg.max_power_kw * 10))
                
            # 温度影响退化
            if power_detected > 0:
                temp_rise = 5.0 * (power_detected / cfg.max_power_kw)
                state.temperature_c = min(80.0, state.temperature_c + temp_rise)
                # 高温加速退化
                if state.temperature_c > 50.0:
                    aging_rate = 1.0 + 0.1 * (state.temperature_c - 50.0) / 30.0
                    state.degradation_factor *= aging_rate
            
            state.status = ApplianceStatus.RUNNING if power_detected > cfg.min_power_kw else ApplianceStatus.IDLE
            
        return dict(self.states)
    
    def get_breakdown(self, hour: int) -> List[Dict]:
        """获取当前时刻电器分解明细。"""
        results = []
        for atype, state in self.states.items():
            cfg = self.appliances[atype]
            contribution_pct = (state.energy_kwh / max(sum(s.energy_kwh for s in self.states.values()), 1.0)) * 100
            
            results.append({
                "type": atype.value,
                "name": self._get_name(atype),
                "max_power_kw": cfg.max_power_kw,
                "current_power_kw": state.power_kw,
                "energy_kwh": state.energy_kwh,
                "soc": state.soc,
                "status": state.status.value,
                "contribution_pct": round(contribution_pct, 2),
                "cost_estimate_cny": state.energy_kwh * 0.65,  # 假设均价 0.65 元/kWh
            })
        return sorted(results, key=lambda x: -x["current_power_kw"])
    
    def _get_name(self, atype: ApplianceType) -> str:
        names = {
            ApplianceType.HEAT_PUMP: "热泵空调",
            ApplianceType.EV_CHARGER: "电动汽车充电桩",
            ApplianceType.BASE_LOAD: "基础家庭负荷",
            ApplianceType.LIGHTING: "照明插座",
            ApplianceType.DISHWASHER: "洗碗机",
            ApplianceType.WATER_HEATER: "电热水器",
        }
        return names.get(atype, atype.value)


# Pydantic models for API serialization
class ApplianceBreakdownRequest(BaseModel):
    total_load_kw: float
    hour: int


class ApplianceSchedulingRequest(BaseModel):
    ev_required_soc: float = 0.9
    ev_departure_hour: int = 8
    heat_pump_target_temp: float = 22.0
    heat_pump_outdoor_temp: float = 5.0


class ApplianceResponse(BaseModel):
    breakdown: List[Dict]
    scheduling_recommendations: Dict[str, Dict]
    estimated_daily_cost_cny: float
    savings_potential_pct: float
