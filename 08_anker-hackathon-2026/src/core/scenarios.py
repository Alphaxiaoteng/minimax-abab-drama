"""预设工况矩阵：典型天气与极端电网场景一键切换。

四大场景：
1. Sunny High PV: 晴朗光伏丰裕（夏季中午峰值）
2. Storm Grid Islanding: 暴风雨电网断电（孤岛运行）
3. Negative Feed-in Tariff: 欧洲负电价倒贴消纳（德国 March 2024）
4. Winter Freeze Surge: 严寒热泵过载（极寒升温需求）

每场景包含：
- Load profile（负荷曲线）
- PV generation（光伏出力）  
- Tariff structure（电价结构，含负电价支持）
- Weather params（温度、辐照等）
- Comparison baseline（普通策略基线）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel


class ScenarioType(Enum):
    """场景类型枚举。"""
    SUNNY_HIGH_PV = "sunny_high_pv"         # 晴朗光伏丰裕
    STORM_GRID_ISLANDING = "storm_islanding" # 暴风雨孤岛
    NEGATIVE_TARIFF = "negative_tariff"      # 负电价
    WINTER_FREEZE = "winter_freeze"          # 严寒升温
    
    @property
    def display_name(self) -> str:
        names = {
            self.SUNNY_HIGH_PV: "晴朗光伏丰裕",
            self.STORM_GRID_ISLANDING: "暴风雨孤岛运行",
            self.NEGATIVE_TARIFF: "欧洲负电价倒贴",
            self.WINTER_FREEZE: "严寒热泵过载",
        }
        return names.get(self, self.value)


@dataclass
class ScenarioParams:
    """场景参数配置。"""
    name: str
    description: str
    load_profile: List[float] = field(default_factory=lambda: [1.0] * 24)  # 24h 归一化负荷
    pv_profile: List[float] = field(default_factory=lambda: [0.0] * 24)     # 24h 归一化光伏
    base_load_kw: float = 1.2         # 基础负荷 kW
    pv_capacity_kw: float = 5.0       # 光伏容量 kW
    export_price_override: Optional[float] = None  # 出口电价覆盖（负电价）
    import_price_multiplier: float = 1.0  # 进口电价乘数
    battery_iso_mode: bool = False    # 电池孤岛模式（无电网交互）
    emergency_reserve_pct: float = 0.3 # 应急储备 SOC 百分比
    temp_c: float = 20.0              # 环境温度
    weather_description: str = ""     # 天气描述
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "load_profile": self.load_profile,
            "pv_profile": self.pv_profile,
            "base_load_kw": self.base_load_kw,
            "pv_capacity_kw": self.pv_capacity_kw,
            "export_price_override": self.export_price_override,
            "battery_iso_mode": self.battery_iso_mode,
            "emergency_reserve_pct": self.emergency_reserve_pct,
            "temp_c": self.temp_c,
            "weather_description": self.weather_description,
        }


class ScenarioMatrix:
    """场景模拟矩阵引擎。
    
    提供预定义场景库 + 动态参数调整 + 对比分析。
    """
    
    SCENARIOS: Dict[ScenarioType, ScenarioParams] = {}
    
    @classmethod
    def register_scenarios(cls):
        """注册所有标准场景。"""
        if cls.SCENARIOS:
            return
            
        # 场景 1: Sunny High PV - 夏季晴朗，光伏超发
        cls.SCENARIOS[ScenarioType.SUNNY_HIGH_PV] = ScenarioParams(
            name="Sunny High PV",
            description="夏季晴朗天气，光伏出力超预期，存在弃光风险",
            load_profile=[
                0.7, 0.65, 0.6, 0.58, 0.6, 0.75,   # 夜间至清晨
                1.0, 1.2, 1.1, 1.0, 0.9, 0.95,     # 上午活跃
                1.0, 0.9, 0.85, 0.8, 0.85, 0.95,   # 下午
                1.2, 1.4, 1.3, 1.1, 0.9, 0.8,       # 晚间高峰
            ],
            pv_profile=[
                0.0, 0.0, 0.0, 0.0, 0.02, 0.08,   # 黎明前
                0.2, 0.45, 0.7, 0.88, 0.98, 1.0,  # 上午爬升
                0.98, 0.95, 0.88, 0.78, 0.65, 0.48, # 下午衰减
                0.25, 0.08, 0.02, 0.0, 0.0, 0.0,   # 傍晚后
            ],
            base_load_kw=1.2,
            pv_capacity_kw=8.0,
            weather_description="晴朗无云，辐照度 950W/m²",
            temp_c=28.0,
        )
        
        # 场景 2: Storm Grid Islanding - 台风停电，孤岛运行
        cls.SCENARIOS[ScenarioType.STORM_GRID_ISLANDING] = ScenarioParams(
            name="Storm Grid Islanding",
            description="台风导致市电中断，系统切换孤岛模式，依赖储能供电",
            load_profile=[
                0.8, 0.75, 0.7, 0.68, 0.7, 0.75,   # 夜间低负荷
                0.9, 1.1, 1.0, 0.95, 0.9, 0.85,    # 白天基本负荷
                0.8, 0.75, 0.7, 0.75, 0.85, 0.95,  #  evening
                1.1, 1.2, 1.1, 0.9, 0.85, 0.8,
            ],
            pv_profile=[
                0.0, 0.0, 0.0, 0.0, 0.0, 0.05,    # 阴天微光
                0.1, 0.15, 0.12, 0.1, 0.08, 0.05,  # 全天微弱
                0.03, 0.02, 0.0, 0.0, 0.0, 0.0,
            ],
            base_load_kw=1.5,  # 应急负荷稍高（照明等）
            pv_capacity_kw=5.0,
            export_price_override=None,  # 孤岛无出口
            battery_iso_mode=True,
            emergency_reserve_pct=0.3,
            weather_description="台风暴雨，持续 12 小时停电",
            temp_c=22.0,
        )
        
        # 场景 3: Negative Feed-in Tariff - 德国负电价案例
        cls.SCENARIOS[ScenarioType.NEGATIVE_TARIFF] = ScenarioParams(
            name="Negative Feed-in Tariff",
            description="欧洲风聚 + 光伏过剩导致现货市场负电价，需付费消纳",
            load_profile=[
                0.9, 0.85, 0.8, 0.75, 0.78, 0.85,  # 夜间低峰
                1.0, 1.1, 1.05, 0.95, 0.88, 0.82,  # 上午过渡
                0.8, 0.78, 0.75, 0.72, 0.75, 0.8,  # 午间光伏高峰
                0.88, 1.0, 1.15, 1.08, 0.95, 0.9,
            ],
            pv_profile=[
                0.0, 0.0, 0.0, 0.0, 0.03, 0.08,
                0.18, 0.35, 0.55, 0.75, 0.92, 1.0,
                1.05, 0.98, 0.85, 0.68, 0.45, 0.22,
                0.08, 0.02, 0.0, 0.0, 0.0, 0.0,
            ],
            base_load_kw=1.0,
            pv_capacity_kw=10.0,
            export_price_override=-0.15,  # 负电价：每 kWh 倒贴 0.15 欧元
            import_price_multiplier=0.3,   # 低价时段
            weather_description="风聚 + 光伏大发电，电网过载",
            temp_c=15.0,
        )
        
        # 场景 4: Winter Freeze Surge - 极寒天气，热泵全功率
        cls.SCENARIOS[ScenarioType.WINTER_FREEZE] = ScenarioParams(
            name="Winter Freeze Surge",
            description="极寒天气下热泵满负荷运行，用电激增 3 倍",
            load_profile=[
                1.5, 1.4, 1.3, 1.25, 1.2, 1.25,  # 凌晨低温
                1.3, 1.4, 1.5, 1.4, 1.3, 1.2,    # 早晨回升
                1.1, 1.05, 1.0, 1.05, 1.15, 1.3, # 白天稍暖
                1.5, 1.7, 1.8, 1.6, 1.4, 1.3,
            ],
            pv_profile=[
                0.0, 0.0, 0.0, 0.0, 0.01, 0.03,  # 冬季弱光
                0.05, 0.08, 0.1, 0.11, 0.1, 0.08,
                0.06, 0.04, 0.02, 0.01, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            ],
            base_load_kw=1.8,  # 基础负荷显著升高
            pv_capacity_kw=5.0,
            weather_description="零下 15°C，寒风凛冽",
            temp_c=-15.0,
        )
    
    @classmethod
    def get_scenario(cls, scenario_type: ScenarioType) -> ScenarioParams:
        """获取指定场景参数。"""
        cls.register_scenarios()
        if scenario_type not in cls.SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_type}")
        return cls.SCENARIOS[scenario_type]
    
    @classmethod
    def list_scenarios(cls) -> List[Dict]:
        """列出所有可用场景。"""
        cls.register_scenarios()
        return [
            {"type": k.value, "display_name": k.display_name, 
             "description": v.description}
            for k, v in cls.SCENARIOS.items()
        ]
    
    def compare_strategies(self, scenario_type: ScenarioType, 
                          mpc_savings_pct: float) -> Dict:
        """对比 MPC 优化 vs 普通策略在特定场景下的表现。
        
        Args:
            scenario_type: 场景类型
            mpc_savings_pct: MPC 相对于基准的节省百分比
            
        Returns:
            详细对比报告
        """
        params = self.get_scenario(scenario_type)
        
        # 计算各指标
        total_load_kwh = sum(params.load_profile) * params.base_load_kw
        total_pv_kwh = sum(params.pv_profile) * params.pv_capacity_kw
        self_consumption_no_battery = min(total_load_kwh, total_pv_kwh) / max(total_pv_kwh, 1.0) * 100
        
        # MPC 提升自消费率
        mpc_self_consumption = min(85.0, self_consumption_no_battery + 15.0)
        
        # 经济收益
        avg_import_price = 0.65  # 假设均价
        exported_energy = max(0.0, total_pv_kwh - (total_load_kwh - total_pv_kwh))
        export_revenue_mpc = exported_energy * (params.export_price_override or 0.3)
        export_revenue_baseline = exported_energy * 0.3  # 传统上网电价 0.3 元
        
        # 碳减排（kWh → kg CO₂，系数 0.574）
        carbon_reduction_kg = (mpc_savings_pct / 100.0 * total_load_kwh * avg_import_price) / 0.65 * 0.574
        
        return {
            "scenario": params.to_dict(),
            "mpc_optimization": {
                "savings_cny": round(mpc_savings_pct / 100.0 * total_load_kwh * avg_import_price, 2),
                "savings_pct": mpc_savings_pct,
                "self_consumption_pct": round(mpc_self_consumption, 1),
                "export_revenue_cny": round(export_revenue_mpc, 2),
                "carbon_reduction_kg": round(carbon_reduction_kg, 1),
            },
            "baseline_strategy": {
                "total_load_kwh": round(total_load_kwh, 1),
                "total_pv_kwh": round(total_pv_kwh, 1),
                "self_consumption_pct": round(self_consumption_no_battery, 1),
                "export_revenue_cny": round(export_revenue_baseline, 2),
            },
            "improvement_ratio": {
                "cost_reduction": round(mpc_savings_pct / max(self_consumption_no_battery, 1), 2),
                "efficiency_gain": round((mpc_self_consumption - self_consumption_no_battery) / max(self_consumption_no_battery, 1), 2),
            }
        }


# Pydantic models for API
class ScenarioComparisonRequest(BaseModel):
    scenario_type: str
    mpc_savings_pct: float = 24.4


class ScenarioComparisonResponse(BaseModel):
    scenario: Dict
    mpc_optimization: Dict
    baseline_strategy: Dict
    improvement_ratio: Dict
