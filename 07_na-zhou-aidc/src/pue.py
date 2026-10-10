"""PUE（Power Usage Effectiveness）分析 —— 数据中心能效指标的分解与评估。

PUE 定义：
    PUE = 设施总功耗 / IT 负载功耗

设施总功耗（本仿真口径）= IT + 制冷 + UPS/配电损耗 (+ 储能往返损耗)。
其中 UPS/配电损耗按 ``ups_loss_ratio`` 摊到 (IT + 制冷) 上：
    ups_loss[t] = ups_loss_ratio * (it_power[t] + cooling[t])

设计原则
--------
* PUE >= 1.0 恒成立：设施功率不可能小于 IT 功率（除零保护后亦然）。
* 储能不改善 PUE：充放电往返损耗只会让设施侧功率上升，PUE 略增；
  其收益体现在电网侧「削峰 + 需量电费 + 峰谷套利」，而非能效本身。
  ``pue_with_vs_without_storage`` 必须诚实地把 ``ΔPUE`` 与 ``Δ电网 kWh`` 并列量化。

``# [INFERENCE]`` 标记：季节性权重、各季节 PUE 乘子、节能杠杆百分比等均为
行业经验/假设值，非本仓库运行计算结果；引用时须与运行时算出的实际数值区分。
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from src.config import STEP_HOURS
from src.types import Schedule

__all__ = [
    "instantaneous_pue",
    "pue_quantiles",
    "annualized_pue",
    "cooling_energy_share",
    "pue_with_vs_without_storage",
    "decompose_facility_power",
    "pue_improvement_levers",
]

# 除零/极小阈值：低于此 IT 功率视为「停机」，避免 PUE 爆量。
_EPS_KW: float = 1e-9


# --------------------------------------------------------------------------
# 瞬时 PUE
# --------------------------------------------------------------------------
def instantaneous_pue(
    it_power_kw: np.ndarray,
    cooling_kw: np.ndarray,
    ups_loss_ratio: float,
) -> np.ndarray:
    """逐时点计算瞬时 PUE。

    Parameters
    ----------
    it_power_kw: IT 负载功率序列（kW）。
    cooling_kw: 制冷系统功率序列（kW）。
    ups_loss_ratio: UPS/配电损耗占 (IT+制冷) 的比例（如 0.03）。

    Returns
    -------
    np.ndarray: PUE 序列，与输入等长，恒 >= 1.0。

    Notes
    -----
    IT=0 的点无法定义 PUE，这里返回 1.0（理论下限）而非 inf/NaN。
    """
    it = np.asarray(it_power_kw, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)

    it_plus_cooling = it + cool
    ups_loss = float(ups_loss_ratio) * it_plus_cooling
    facility = it_plus_cooling + ups_loss

    # 保护除零：仅在 IT>阈值处相除，其余置为 1.0。
    pue = np.ones_like(it, dtype=float)
    mask = it > _EPS_KW
    np.divide(facility, it, out=pue, where=mask)

    return np.maximum(pue, 1.0)


# --------------------------------------------------------------------------
# PUE 分位数
# --------------------------------------------------------------------------
def pue_quantiles(
    pue: np.ndarray,
    probs: Sequence[float] = (0.05, 0.5, 0.95),
) -> Dict[str, float]:
    """返回 PUE 分布的分位数，键形如 ``p05`` / ``p50`` / ``p95``。

    Parameters
    ----------
    pue: PUE 序列。
    probs: 分位点（0~1）。

    Returns
    -------
    Dict[str, float]: 键为 ``p{百分位:02d}``，值为对应分位数。
    """
    arr = np.asarray(pue, dtype=float)
    if arr.size == 0:
        raise ValueError("pue 序列为空，无法计算分位数")

    quantiles = np.quantile(arr, np.asarray(list(probs), dtype=float))
    result: Dict[str, float] = {}
    for prob, value in zip(probs, np.atleast_1d(quantiles)):
        key = "p{:02d}".format(int(round(float(prob) * 100)))
        result[key] = float(value)
    return result


# --------------------------------------------------------------------------
# 年化 PUE（明确加权假设，非实测外推）
# --------------------------------------------------------------------------
def annualized_pue(
    daily_pue: np.ndarray,
    summer_weight: float = 0.30,
    winter_weight: float = 0.20,
    transition_weight: float = 0.50,
) -> float:
    """把单日 PUE 外推为年化 PUE —— 一个文档化的季节性加权平均。

    ⚠️ 这不是「测得的年 PUE」，而是把仿真代表日按季节天数加权后的估计值，
    所有季节乘子均为 ``# [INFERENCE]`` 经验假设，读者须据此理解误差。

    假设（``# [INFERENCE]``）
    -----------------------
    * 夏季制冷负荷最高，年化乘子 1.08；
    * 过渡季次之，乘子 1.02；
    * 冬季可借助自然冷源，乘子 0.96；
    * 三季「代表日」天数权重默认 30% / 50% / 20%（和须为 1）。

    Parameters
    ----------
    daily_pue: 单日 PUE 序列。
    summer_weight, winter_weight, transition_weight: 三季天数权重。

    Returns
    -------
    float: 年化 PUE 估计（应落在 [1.0, ~2.0]）。

    Raises
    ------
    ValueError: 权重之和不为 1.0，或输入为空。
    """
    weights = (summer_weight, transition_weight, winter_weight)
    if not np.isclose(sum(weights), 1.0):
        raise ValueError("夏/过渡/冬权重之和必须为 1.0，当前为 {}".format(sum(weights)))

    arr = np.asarray(daily_pue, dtype=float)
    if arr.size == 0:
        raise ValueError("daily_pue 为空")

    # [INFERENCE] 各季节相对代表日的 PUE 乘子。
    seasonal_factor = {
        "summer": 1.08,
        "transition": 1.02,
        "winter": 0.96,
    }
    weighted_factor = (
        float(summer_weight) * seasonal_factor["summer"]
        + float(transition_weight) * seasonal_factor["transition"]
        + float(winter_weight) * seasonal_factor["winter"]
    )

    avg_daily = float(np.mean(arr))
    return float(avg_daily * weighted_factor)


# --------------------------------------------------------------------------
# 制冷能耗占设施总能量之比
# --------------------------------------------------------------------------
def cooling_energy_share(
    it_power: np.ndarray,
    cooling_kw: np.ndarray,
    ups_loss_ratio: float,
) -> float:
    """整日累计口径下，制冷能耗占设施总能耗的比例（0~1）。

    facility_energy = sum(it + cooling) * (1 + ups_loss_ratio)
    cooling_share   = sum(cooling) / facility_energy
    """
    it = np.asarray(it_power, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)

    it_plus_cooling_kwh = float(np.sum(it + cool)) * STEP_HOURS
    facility_kwh = it_plus_cooling_kwh * (1.0 + float(ups_loss_ratio))
    if facility_kwh <= 0.0:
        return 0.0

    cooling_kwh = float(np.sum(cool)) * STEP_HOURS
    return float(cooling_kwh / facility_kwh)


# --------------------------------------------------------------------------
# 有/无储能的 PUE 对比（诚实量化权衡）
# --------------------------------------------------------------------------
def pue_with_vs_without_storage(
    it_power: np.ndarray,
    cooling_kw: np.ndarray,
    schedule_opt: Schedule,
    schedule_base: Schedule,
    ups_loss_ratio: float = 0.0,
) -> Dict[str, Any]:
    """量化「优化调度(带储能)」相对「基线(无/零净储能)」的 PUE 与电网能耗差异。

    结论口径（不得粉饰）
    --------------------
    储能带来往返损耗 → 设施侧功率上升 → ``ΔPUE >= 0``（PUE 变差或持平）；
    收益体现在电网侧峰值/需量/峰谷电价，而非能效。函数把 ``ΔPUE`` 与
    ``Δ电网 kWh`` 并列返回，并给出文字解读。

    PUE 口径：设施 = IT + 制冷 + UPS 损耗 + 储能往返损耗；
    基线用 ``schedule_base.battery_loss_kw``（净放为零时≈0），
    优化用 ``schedule_opt.battery_loss_kw``。UPS 用统一 ``ups_loss_ratio``
    （基线与优化相同，不影响 ΔPUE，仅影响绝对值）。

    Returns
    -------
    Dict[str, Any]: 见下方键；``interpretation`` 为中文结论。
    """
    it = np.asarray(it_power, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)

    # 储能往返损耗（kW）——直接复用冻结接口 Schedule.battery_loss_kw。
    loss_opt = np.asarray(schedule_opt.battery_loss_kw, dtype=float)
    loss_base = np.asarray(schedule_base.battery_loss_kw, dtype=float)

    base_facility = (it + cool) * (1.0 + float(ups_loss_ratio)) + loss_base
    opt_facility = (it + cool) * (1.0 + float(ups_loss_ratio)) + loss_opt

    pue_base = np.maximum(base_facility / np.where(it > _EPS_KW, it, np.inf), 1.0)
    pue_opt = np.maximum(opt_facility / np.where(it > _EPS_KW, it, np.inf), 1.0)

    avg_pue_base = float(np.mean(pue_base))
    avg_pue_opt = float(np.mean(pue_opt))
    delta_pue = avg_pue_opt - avg_pue_base

    # 电网取电（kWh）= Σ grid_import * step_hours。
    grid_opt_kwh = float(np.sum(np.asarray(schedule_opt.grid_import_kw, dtype=float))) * STEP_HOURS
    grid_base_kwh = float(np.sum(np.asarray(schedule_base.grid_import_kw, dtype=float))) * STEP_HOURS
    delta_grid_kwh = grid_opt_kwh - grid_base_kwh

    interpretation = (
        "储能使设施侧平均 PUE 由 {b:.4f} 变为 {o:.4f}（ΔPUE={d:+.4f}，往返损耗所致，PUE 未改善）；"
        "同期电网取电由 {gb:.1f} kWh 变为 {go:.1f} kWh（Δ={dg:+.1f} kWh）。"
        "储能的收益在于削峰降需量与峰谷套利，而非提升能效；两者必须并列汇报。"
    ).format(
        b=avg_pue_base,
        o=avg_pue_opt,
        d=delta_pue,
        gb=grid_base_kwh,
        go=grid_opt_kwh,
        dg=delta_grid_kwh,
    )

    return {
        "pue_optimized": avg_pue_opt,
        "pue_baseline": avg_pue_base,
        "delta_pue": delta_pue,
        "grid_kwh_optimized": grid_opt_kwh,
        "grid_kwh_baseline": grid_base_kwh,
        "delta_grid_kwh": delta_grid_kwh,
        "interpretation": interpretation,
    }


# --------------------------------------------------------------------------
# 设施功率分解（堆叠面积图组件）
# --------------------------------------------------------------------------
def decompose_facility_power(
    it_power: np.ndarray,
    cooling_kw: np.ndarray,
    schedule: Schedule,
    ups_loss_ratio: float = 0.0,
) -> Dict[str, np.ndarray]:
    """把设施总功率拆成可堆叠的 4 个分量，供画 stacked-area 图。

    分量（单位 kW，逐时点）
    ----------------------
    * ``it``:          IT 负载
    * ``cooling``:     制冷
    * ``ups_loss``:    UPS/配电损耗 = ups_loss_ratio * (it + cooling)
    * ``battery_loss``: 储能往返损耗（复用 Schedule.battery_loss_kw）

    四者之和即设施侧瞬时功率，除以 ``it`` 即含储能的 PUE。
    """
    it = np.asarray(it_power, dtype=float)
    cool = np.asarray(cooling_kw, dtype=float)

    ups = float(ups_loss_ratio) * (it + cool)
    battery = np.asarray(schedule.battery_loss_kw, dtype=float)

    return {
        "it": it.copy(),
        "cooling": cool.copy(),
        "ups_loss": ups,
        "battery_loss": battery,
    }


# --------------------------------------------------------------------------
# PUE 提升杠杆清单（有序，均带 [INFERENCE]）
# --------------------------------------------------------------------------
def pue_improvement_levers() -> List[Dict[str, Any]]:
    """返回按「预期节能幅度」降序排列的 PUE 杠杆清单。

    每条含：名称、原理、``pue_reduction_pct`` 区间（``# [INFERENCE]`` 经验值）、
    与储能关系说明。所有百分比为行业经验区间，非本仿真计算结果，且不提供虚构引用。
    """
    levers: List[Dict[str, Any]] = [
        {
            "name": "冷板式液冷 (cold-plate liquid cooling)",
            "pue_reduction_pct": (10.0, 25.0),  # [INFERENCE]
            "mechanism": "高热密度 AI 机柜以液体直接带走热量，风扇/冷机负荷大幅下降。",
            "note": "对 AIDC 训练集群收益最显著。",  # [INFERENCE]
        },
        {
            "name": "自然冷却 / free cooling",
            "pue_reduction_pct": (5.0, 20.0),  # [INFERENCE]
            "mechanism": "室外低温时直接/间接蒸发换热，减少压缩制冷运行时长。",
            "note": "冬季与过渡季贡献最大，与冬季 PUE 乘子 0.96 呼应。",  # [INFERENCE]
        },
        {
            "name": "AI 智能温控 (model-predictive cooling control)",
            "pue_reduction_pct": (5.0, 15.0),  # [INFERENCE]
            "mechanism": "ML 预测机柜热负荷，联动调节水泵/冷塔/风机转速，消除过冷。",
            "note": "与瞬态算力峰值耦合时收益更稳。",  # [INFERENCE]
        },
        {
            "name": "提高送风/供水温度 (raise supply air/chill temp)",
            "pue_reduction_pct": (2.0, 8.0),  # [INFERENCE]
            "mechanism": "在 ASHRAE 允许包络内抬高冷媒温度，提升冷机 COP。",
            "note": "实施成本低、见效快。",  # [INFERENCE]
        },
        {
            "name": "储能选址/削峰 (storage siting for demand charge)",
            "pue_reduction_pct": (-2.0, 0.0),  # [INFERENCE]：往返损耗使 PUE 略升
            "mechanism": "储能目标是降需量电费与峰谷套利，不改善能效；PUE 反而略增。",
            "note": "务必在报告中如实标注其 PUE 代价（见 pue_with_vs_without_storage）。",
        },
    ]
    return levers