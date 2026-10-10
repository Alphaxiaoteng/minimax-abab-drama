"""分时电价（TOU）序列与电费计算 —— 电量电费 + 最大需量电费。

本模块把 ``config.TariffParams`` 的四档电价（谷 / 平 / 峰 / 尖峰）展开为
96 步价格序列，并提供报表与 LP 目标所需的电费函数：

- ``price_series``: 整日分时电价序列（元/kWh），委托 ``config.price_series``。
- ``energy_cost``: 电量电费（元）= Σ power[t] · price[t] · step_hours。
- ``demand_charge``: 最大需量电费（元）。需量电价按月申报（元/kW/月），
  单日仿真按 ``days / 30`` 线性折算到仿真地平线。
- ``total_tou_cost``: 电量电费 + 折算需量电费。
- ``tou_breakdown``: 按电价档位拆分电费与电量，供报表表格使用。
- ``arbitrage_headroom``: 峰谷套利的理论日收益上界。  # [INFERENCE]
"""
from __future__ import annotations

from typing import Dict, Union

import numpy as np

from src.config import (
    N_STEPS,
    STEP_HOURS,
    BatteryParams,
    TariffParams,
    price_level,
)
from src.config import price_series as _config_price_series

ArrayLike = Union[np.ndarray, list]

LEVELS = ("valley", "flat", "peak", "sharp")

__all__ = [
    "ArrayLike",
    "LEVELS",
    "price_series",
    "demand_charge",
    "energy_cost",
    "total_tou_cost",
    "tou_breakdown",
    "peak_valley_spread",
    "arbitrage_headroom",
]


# --------------------------------------------------------------------------
# 价格序列
# --------------------------------------------------------------------------
def price_series(tariff: TariffParams, n_steps: int = N_STEPS) -> np.ndarray:
    """整日分时电价序列（元/kWh），长度 ``n_steps``（默认 96）。

    第 t 步对应时刻 ``t * STEP_HOURS``，档位由 ``config.TOU_WINDOWS`` 决定；
    本函数是 ``tariff.price_at`` 的向量化封装（委托 ``config.price_series``）。
    """
    return _config_price_series(tariff, n_steps)


# --------------------------------------------------------------------------
# 需量电费（基本电费之最大需量口径）
# --------------------------------------------------------------------------
def demand_charge(
    peak_kw: float,
    demand_charge_per_kw: float,
    days: float = 1.0,
) -> float:
    """最大需量电费（元），按月单价折算到仿真地平线。

    折算公式::

        需量电费 = per_kw_month * days / 30 * peak_kw

    ``demand_charge_per_kw``（元/kW/月）按每月 30 天计，仿真覆盖 ``days`` 天
    则按 ``days / 30`` 线性分摊；单日仿真取 ``days = 1``，即一天的需量电费
    只计整月基本电费的 1/30。需量本应以「月内最大需量」计费，这里用仿真
    窗口内的并网点取电峰值近似。
    """
    peak = float(peak_kw)
    per_kw = float(demand_charge_per_kw)
    horizon = float(days)
    if not (np.isfinite(peak) and np.isfinite(per_kw) and np.isfinite(horizon)):
        raise ValueError("peak_kw / demand_charge_per_kw / days 必须为有限值")
    if peak < 0.0:
        raise ValueError("peak_kw 不能为负，实际为 {!r}".format(peak))
    if horizon <= 0.0:
        raise ValueError("days 必须为正，实际为 {!r}".format(horizon))
    return per_kw * horizon / 30.0 * peak


# --------------------------------------------------------------------------
# 电量电费与总电费
# --------------------------------------------------------------------------
def _as_series(values: ArrayLike, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError("{} 必须为一维序列".format(name))
    return arr


def energy_cost(
    power_series_kw: ArrayLike,
    prices: ArrayLike,
    step_hours: float = STEP_HOURS,
) -> float:
    """电量电费（元）= Σ power[t] · price[t] · step_hours。

    ``power_series_kw`` 为并网点取电功率（kW，非负），与 ``prices`` 等长；
    ``step_hours`` 为单步时长（h），功率 kW × 时长 h = 电量 kWh。
    """
    power = _as_series(power_series_kw, "power_series_kw")
    prices_arr = _as_series(prices, "prices")
    if power.shape != prices_arr.shape:
        raise ValueError(
            "功率与价格序列长度不一致: {} vs {}".format(power.size, prices_arr.size)
        )
    if (power < 0.0).any():
        raise ValueError("power_series_kw 存在负值，取电功率应为非负")
    return float(np.dot(power, prices_arr) * float(step_hours))


def total_tou_cost(
    power_series_kw: ArrayLike,
    prices: ArrayLike,
    peak_kw: float,
    demand_charge_per_kw: float,
    days: float = 1.0,
    step_hours: float = STEP_HOURS,
) -> float:
    """分时口径总电费（元）= 电量电费 + 折算后的最大需量电费。"""
    return energy_cost(power_series_kw, prices, step_hours) + demand_charge(
        peak_kw, demand_charge_per_kw, days
    )


# --------------------------------------------------------------------------
# 档位拆分（报表用）
# --------------------------------------------------------------------------
def tou_breakdown(
    power_series_kw: ArrayLike,
    prices: ArrayLike,
    step_hours: float = STEP_HOURS,
) -> Dict[str, float]:
    """按电价档位拆分电量电费与电量（报表表格用）。

    档位归属按步序号还原时刻 ``i * step_hours`` 后查 ``config.price_level``，
    与 ``price_series`` 的构造方式一致（日仿真下逐步成立）。

    Returns
    -------
    dict
        ``{level}_cost``: 该档位电量电费（元）；
        ``{level}_energy_kwh``: 该档位电量（kWh）；
        ``total_cost``: 四档之和（== ``energy_cost``），level ∈ valley/flat/peak/sharp。

        中文列名（谷/平/峰/尖峰）由报表层用 ``config.LEVEL_CN`` 映射。
    """
    power = _as_series(power_series_kw, "power_series_kw")
    prices_arr = _as_series(prices, "prices")
    if power.shape != prices_arr.shape:
        raise ValueError("功率与价格序列长度不一致")
    energy = power * float(step_hours)
    cost = energy * prices_arr
    hours = np.arange(power.size) * float(step_hours)
    result: Dict[str, float] = {}
    for level in LEVELS:
        mask = np.array([price_level(h) == level for h in hours])
        result["{}_cost".format(level)] = float(cost[mask].sum())
        result["{}_energy_kwh".format(level)] = float(energy[mask].sum())
    result["total_cost"] = float(cost.sum())
    return result


# --------------------------------------------------------------------------
# 套利上界
# --------------------------------------------------------------------------
def peak_valley_spread(prices: ArrayLike) -> float:
    """峰谷价差（元/kWh）= max(price) − min(price)。"""
    prices_arr = _as_series(prices, "prices")
    if prices_arr.size == 0:
        raise ValueError("prices 不能为空")
    return float(prices_arr.max() - prices_arr.min())


def arbitrage_headroom(
    prices: ArrayLike,
    battery_params: BatteryParams,
    step_hours: float = STEP_HOURS,
) -> float:
    """理论最大日套利收益（元/天）：``min(可用能量, 谷段可充电量) × 价差``。

    公式::

        valley_hours   = Σ [price_level(t·step_hours) == "valley"] · step_hours
        valley_kwh     = p_charge_max_kw · valley_hours
        headroom       = min(usable_kwh, valley_kwh) · (max_price - min_price)

    - ``usable_kwh`` = capacity_kwh · (soc_max − soc_min)，单循环可搬运能量；
    - ``valley_kwh`` 是谷段时长受充电功率上限约束时实际能充进的最大电量，
      即「低价窗口装得下多少」。

    线性规划可达上界，未计效率与老化：忽略往返效率（eta_charge · eta_discharge）、
    SOC 初值、峰/尖峰放电功率与放电时长约束，因此严格偏乐观，只用于给报表
    标注「套利天花板」量级。  # [INFERENCE]
    """
    prices_arr = _as_series(prices, "prices")
    if prices_arr.size == 0:
        raise ValueError("prices 不能为空")
    spread = peak_valley_spread(prices_arr)
    hours = np.arange(prices_arr.size) * float(step_hours)
    valley_steps = sum(1 for h in hours if price_level(h) == "valley")
    valley_kwh = float(battery_params.p_charge_max_kw) * valley_steps * float(step_hours)
    usable = float(battery_params.usable_kwh)
    return min(usable, valley_kwh) * spread