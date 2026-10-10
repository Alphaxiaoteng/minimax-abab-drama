"""共享结果容器 —— 调度解与 KPI。

所有下游模块（optimizer / pue / simulate / report）都依赖这里的字段名，
字段一经确定即视为冻结接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np


@dataclass
class Schedule:
    """一次仿真的完整调度轨迹。

    数组长度均为 ``N_STEPS``（96 点 / 15 分钟）。

    Attributes
    ----------
    strategy:
        策略标识（``baseline`` / ``greedy`` / ``optimal``）。
    charge_kw:
        储能充电功率（kW，>=0）。
    discharge_kw:
        储能放电功率（kW，>=0）。
    soc:
        每步结束时的荷电状态（0~1）。
    grid_import_kw:
        电网取电功率（kW）。
    it_power_kw:
        IT 设备功率（kW）。
    cooling_kw:
        制冷功率（kW）。
    objective_value:
        LP 目标函数值（元）；非 LP 策略填该策略自身的等效成本。
    status:
        求解状态字符串（``Optimal`` / ``Infeasible`` / ``baseline`` ...）。
    """

    strategy: str
    charge_kw: np.ndarray
    discharge_kw: np.ndarray
    soc: np.ndarray
    grid_import_kw: np.ndarray
    it_power_kw: np.ndarray
    cooling_kw: np.ndarray
    objective_value: float = 0.0
    status: str = "unknown"

    @property
    def battery_loss_kw(self) -> np.ndarray:
        """储能往返损耗（kW）：以电网侧计，充放电效率差形成的有功损失。"""
        return self.charge_kw * (1.0 - _ETA_C) + self.discharge_kw * (1.0 / _ETA_D - 1.0)

    @property
    def facility_power_kw(self) -> np.ndarray:
        """数据中心整体用电（含 IT、制冷、UPS 损耗），不含储能。"""
        return self.it_power_kw + self.cooling_kw

    @property
    def total_power_kw(self) -> np.ndarray:
        """并网点总功率（含储能充放电，充电为正）。"""
        return self.grid_import_kw

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "charge_kw": self.charge_kw.tolist(),
            "discharge_kw": self.discharge_kw.tolist(),
            "soc": self.soc.tolist(),
            "grid_import_kw": self.grid_import_kw.tolist(),
            "it_power_kw": self.it_power_kw.tolist(),
            "cooling_kw": self.cooling_kw.tolist(),
            "objective_value": float(self.objective_value),
            "status": self.status,
        }


@dataclass
class KPIs:
    """单策略的 KPI 汇总。所有金额单位：元（单日）。"""

    strategy: str = "unknown"
    electricity_cost: float = 0.0
    demand_cost: float = 0.0
    total_cost: float = 0.0
    degradation_cost: float = 0.0
    peak_grid_kw: float = 0.0
    valley_grid_kw: float = 0.0
    peak_valley_spread_kw: float = 0.0
    load_factor: float = 0.0
    peak_shaved_ratio: float = 0.0
    arbitrage_saving: float = 0.0
    saved_energy_kwh: float = 0.0
    avg_pue: float = 0.0
    max_pue: float = 0.0
    co2_saved_kg: float = 0.0
    solver_seconds: float = 0.0
    extra: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "strategy": self.strategy,
            "electricity_cost": float(self.electricity_cost),
            "demand_cost": float(self.demand_cost),
            "total_cost": float(self.total_cost),
            "degradation_cost": float(self.degradation_cost),
            "peak_grid_kw": float(self.peak_grid_kw),
            "valley_grid_kw": float(self.valley_grid_kw),
            "peak_valley_spread_kw": float(self.peak_valley_spread_kw),
            "load_factor": float(self.load_factor),
            "peak_shaved_ratio": float(self.peak_shaved_ratio),
            "arbitrage_saving": float(self.arbitrage_saving),
            "saved_energy_kwh": float(self.saved_energy_kwh),
            "avg_pue": float(self.avg_pue),
            "max_pue": float(self.max_pue),
            "co2_saved_kg": float(self.co2_saved_kg),
            "solver_seconds": float(self.solver_seconds),
        }
        out.update({k: float(v) for k, v in self.extra.items()})
        return out

    def rows(self) -> List[str]:
        """给 Markdown 表格用的 (指标, 数值) 列表。"""
        return [
            ("策略", self.strategy),
            ("电度电费 (元/日)", "{:.2f}".format(self.electricity_cost)),
            ("需量电费 (元/日)", "{:.2f}".format(self.demand_cost)),
            ("储能老化成本 (元/日)", "{:.2f}".format(self.degradation_cost)),
            ("综合成本 (元/日)", "{:.2f}".format(self.total_cost)),
            ("电网峰值 (kW)", "{:.1f}".format(self.peak_grid_kw)),
            ("削峰比例", "{:.2%}".format(self.peak_shaved_ratio)),
            ("负荷率", "{:.3f}".format(self.load_factor)),
            ("平均 PUE", "{:.4f}".format(self.avg_pue)),
            ("最大 PUE", "{:.4f}".format(self.max_pue)),
            ("购电量变化 (kWh/日)", "{:.1f}".format(self.saved_energy_kwh)),
            ("对应 CO2 变化 (kg/日)", "{:.1f}".format(self.co2_saved_kg)),
        ]


# 效率默认值仅在 battery_loss_kw 中作为兜底使用；真实计算请用 BatteryParams。
_ETA_C = 0.95
_ETA_D = 0.95
