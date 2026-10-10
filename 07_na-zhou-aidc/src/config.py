"""全局仿真配置 —— 钠电储能 / AIDC 数据中心 / 分时电价。

本模块是整个项目的**冻结接口**：所有下游模块（battery / workload / tariff /
optimizer / pue / simulate / report）只通过这里定义的参数对象互相通信。

时间基准
--------
一天离散为 ``N_STEPS = 96`` 个 15 分钟步长（``STEP_HOURS = 0.25``）。
所有功率序列长度均为 96，单位 kW；能量单位 kWh。

参数取值说明
------------
钠离子电池（Na-ion）面向电网侧储能的实际工程区间取值：
宽温域（-30~60℃ 可放电）、低温保持率优于 LFP、功率密度高、能量密度略低、
不含锂/钴/镍（部分体系），循环寿命约 3000~5000 次（80% DoD）。
参数按「2000 kWh / 500 kW」工商业储能柜组规模设定。
数值来源标注：``# [INFERENCE]`` 表示工程推断值，非运行时计算所得。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

# --------------------------------------------------------------------------
# 时间基准
# --------------------------------------------------------------------------
N_STEPS: int = 96
STEP_HOURS: float = 0.25

# 电网平均碳排放因子（kgCO2/kWh），中国区域电网平均值。  # [INFERENCE]
GRID_CO2_FACTOR: float = 0.581


# --------------------------------------------------------------------------
# 参数对象
# --------------------------------------------------------------------------
@dataclass
class BatteryParams:
    """钠离子电池储能参数。

    Attributes
    ----------
    capacity_kwh: 额定容量（kWh）。
    p_charge_max_kw: 最大充电功率（kW）。
    p_discharge_max_kw: 最大放电功率（kW）。
    soc_min / soc_max: SOC 运行区间（0~1），越界会显著加速老化。
    soc_init: 调度起始 SOC。
    eta_charge / eta_discharge: 单向效率（往返效率 = 两者之积）。
    cycle_life: 循环寿命（等效全循环次数，80% DoD 基准）。
    capex_per_kwh: 单位容量初始投资（元/kWh），用于度电老化成本折算。
    om_cost_per_kwh: 单位吞吐运维成本（元/kWh）。
    """

    capacity_kwh: float = 2000.0
    p_charge_max_kw: float = 500.0
    p_discharge_max_kw: float = 500.0
    soc_min: float = 0.10
    soc_max: float = 0.90
    soc_init: float = 0.50
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    cycle_life: float = 4000.0
    capex_per_kwh: float = 900.0
    om_cost_per_kwh: float = 0.02

    @property
    def usable_kwh(self) -> float:
        """可用能量窗口（kWh）。"""
        return self.capacity_kwh * (self.soc_max - self.soc_min)

    @property
    def round_trip_efficiency(self) -> float:
        return self.eta_charge * self.eta_discharge


@dataclass
class DataCenterParams:
    """AIDC 数据中心负荷与供配电参数。

    Attributes
    ----------
    it_base_kw: 常态 IT 负载（kW）。
    it_peak_kw: IT 负载上限，即算力满发功率（kW）。
    cooling_ratio_base: 制冷功耗 / IT 功耗 的名义比例（AHU/冷冻水混合）。
    pue_target: 设计目标 PUE。
    transformer_limit_kw: 变压器容量（kW），并网点的硬约束来源。
    ups_loss_ratio: UPS 与配电损耗占 IT+制冷 的比例。
    grid_connection_kw: 并网点容量（kW），通常等于或小于变压器容量。
    demand_charge_per_kw: 最大需量电费单价（元/kW/月）。
    """

    it_base_kw: float = 3000.0
    it_peak_kw: float = 9000.0
    cooling_ratio_base: float = 0.32
    pue_target: float = 1.25
    transformer_limit_kw: float = 8000.0
    ups_loss_ratio: float = 0.03
    grid_connection_kw: float = 8000.0
    demand_charge_per_kw: float = 42.0

    @property
    def facility_limit_kw(self) -> float:
        """并网点允许的最大取电功率（kW）。"""
        return min(self.transformer_limit_kw, self.grid_connection_kw)


@dataclass
class TariffParams:
    """工业分时电价（元/kWh）。

    四档：谷 / 平 / 峰 / 尖峰。时段划分见 ``TOU_WINDOWS``。
    """

    valley_price: float = 0.30
    flat_price: float = 0.62
    peak_price: float = 0.98
    sharp_price: float = 1.28

    def price_at(self, step_index: int) -> float:
        """返回第 ``step_index`` 步（0..95）的电价。"""
        hour = (step_index % N_STEPS) * STEP_HOURS
        return price_for_hour(self, hour)


# 分时电价时段表：(起始小时, 结束小时, 档位名)
# 尖峰出现在迎峰度夏/度冬的双高时段，此处按「上午 10:00-11:00 + 晚间 19:00-21:00」模拟。
TOU_WINDOWS: Tuple[Tuple[float, float, str], ...] = (
    (0.0, 7.0, "valley"),     # 23:00-07:00 实际跨零点，0:00-7:00 属谷段
    (7.0, 8.0, "flat"),
    (8.0, 10.0, "peak"),
    (10.0, 11.0, "sharp"),
    (11.0, 13.0, "flat"),
    (13.0, 19.0, "peak"),
    (19.0, 21.0, "sharp"),
    (21.0, 23.0, "peak"),
    (23.0, 24.0, "valley"),
)

LEVEL_CN: Dict[str, str] = {
    "valley": "谷",
    "flat": "平",
    "peak": "峰",
    "sharp": "尖峰",
}


def price_level(hour: float) -> str:
    """给定小时（0~24，可含小数），返回所属电价档位名。"""
    h = float(hour) % 24.0
    for start, end, name in TOU_WINDOWS:
        if start <= h < end:
            return name
    return "flat"


def price_for_hour(tariff: TariffParams, hour: float) -> float:
    """给定小时返回电价（元/kWh）。"""
    return float(getattr(tariff, "{}_price".format(price_level(hour))))


def price_series(tariff: TariffParams, n_steps: int = N_STEPS) -> np.ndarray:
    """生成整日分时电价序列。"""
    return np.array([price_for_hour(tariff, i * STEP_HOURS) for i in range(n_steps)], dtype=float)


# --------------------------------------------------------------------------
# 情景
# --------------------------------------------------------------------------
@dataclass
class Scenario:
    """一个仿真情景：负荷形态 + 设备/电价参数。"""

    name: str = "baseline_day"
    seed: int = 42
    description: str = ""
    battery: BatteryParams = field(default_factory=lambda: BatteryParams())
    datacenter: DataCenterParams = field(default_factory=lambda: DataCenterParams())
    tariff: TariffParams = field(default_factory=lambda: TariffParams())
    # 负荷形态控制：瞬态算力峰值的强度
    spike_count: int = 1
    spike_scale: float = 0.35
    extreme_spike: bool = False

    def price_series(self, n_steps: int = N_STEPS) -> np.ndarray:
        return price_series(self.tariff, n_steps)

    @property
    def params(self) -> Dict[str, object]:
        return {
            "battery": self.battery,
            "datacenter": self.datacenter,
            "tariff": self.tariff,
        }


# --------------------------------------------------------------------------
# 默认工厂
# --------------------------------------------------------------------------
def default_battery() -> BatteryParams:
    return BatteryParams()


def default_datacenter() -> DataCenterParams:
    return DataCenterParams()


def default_tariff() -> TariffParams:
    return TariffParams()


def default_scenarios() -> List[Scenario]:
    """三个递进情景：平稳日 / 瞬态尖峰日 / 极端峰值日。"""
    return [
        Scenario(
            name="baseline_day",
            seed=42,
            description="常态算力日：1 次中等训练峰值，电网峰值低于变压器容量。",
            spike_count=1,
            spike_scale=0.30,
            extreme_spike=False,
        ),
        Scenario(
            name="transient_spike",
            seed=7,
            description="瞬态算力日：多次 AI 训练任务叠加，出现多个 15~120 分钟尖峰。",
            spike_count=6,
            spike_scale=0.55,
            extreme_spike=False,
        ),
        Scenario(
            name="extreme_peak",
            seed=2026,
            # 峰值 12161.6 kW − 电网限额 8000 kW = 4161.6 kW 最小放电需求；
            # 取 5500 kW（~24% 裕度）+ 22000 kWh（≈4h@5500kW）覆盖尖峰与 SOC/终端约束。
            description="极端峰值日：单个大模型任务满发 ~1.5h，叠加背景波动；钠电储能替代变压器扩容。",
            spike_count=3,
            spike_scale=0.40,
            extreme_spike=True,
            battery=BatteryParams(
                capacity_kwh=22000.0,
                p_charge_max_kw=5500.0,
                p_discharge_max_kw=5500.0,
                soc_min=0.10,
                soc_max=0.90,
                soc_init=0.50,
                eta_charge=0.95,
                eta_discharge=0.95,
                cycle_life=4000.0,
                capex_per_kwh=900.0,
                om_cost_per_kwh=0.02,
            ),
        ),
    ]


def scenario_by_name(name: str) -> Scenario:
    for s in default_scenarios():
        if s.name == name:
            return s
    raise KeyError(
        "unknown scenario {!r}; available: {}".format(
            name, ", ".join(s.name for s in default_scenarios())
        )
    )
