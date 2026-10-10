"""钠离子电池（Na-ion）储能模型 —— SOC 动态、功率/效率约束与循环老化成本。

本模块只负责「单体电池物理 + 老化经济性」，不涉及任何优化/调度逻辑，
因此可被 `optimizer`（LP 系数）、`pue`（损耗分摊）与 `simulate`（闭环校验）重复复用。

符号约定（SIGN CONVENTION，全模块一致）
---------------------------------------
* 正功率 = 充电（从电网吸收能量，SOC 上升）
* 负功率 = 放电（向负载注入能量，SOC 下降）

SOC 递推（``soc[t]`` 为第 t 步「结束时」的 SOC，`soc[-1]` 表示起始状态）
---------------------------------------------------------------------
    soc[t] = soc[t-1] + (eta_charge * charge[t] - discharge[t] / eta_discharge)
                        * step_hours / capacity_kwh

即放电时必须多放出 ``1/eta_discharge`` 倍的电池内部能量，充电时只有
``eta_charge`` 倍进入电池内部；两者之积 ``round_trip_efficiency`` 为往返效率。

钠离子电池工程特性（用于报告中与其他化学体系对比）
---------------------------------------------------
* 宽温域工作：-40 ℃ ~ +60 ℃ 可放电，-20 ℃ 仍可保持较高可用容量，
  低温性能显著优于 LFP（磷酸铁锂）。                          # [INFERENCE]
* 倍率性能好、功率密度高，适合 AIDC 的秒级/分钟级瞬态算力峰值；
  但能量密度（约 100~160 Wh/kg）低于 LFP（约 160~200 Wh/kg），
  同容量占地/重量更大。                                       # [INFERENCE]
* 循环寿命约 3000~5000 次（80% DoD 基准）；本模块默认取 4000 次。  # [INFERENCE]
* 不含锂、钴等稀缺/敏感元素，原料（钠盐）储量丰富、成本稳定，
  且允许深度放电至 0 V 运输，安全性好。                        # [INFERENCE]

⚠️ 上述 ``# [INFERENCE]`` 标注的数字为文献经验值，并非本仓库运行计算结果；
报告中引用时须与会话计算出的实际数值严格区分。
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from src.config import STEP_HOURS, BatteryParams

__all__ = [
    "validate_params",
    "soc_bounds",
    "soc_energy_kwh",
    "simulate_soc",
    "power_to_soc_delta",
    "max_deliverable_kw",
    "max_absorbable_kw",
    "degradation_cost",
    "throughput_cost_per_kwh",
]

# SOC 数值容差：浮点累加误差不应被误判为越界。
_SOC_TOL: float = 1e-9


# --------------------------------------------------------------------------
# 参数校验与边界
# --------------------------------------------------------------------------
def validate_params(params: BatteryParams) -> None:
    """校验电池参数合法性，非法即抛 ``ValueError``。

    检查项：
      1. ``capacity_kwh > 0``
      2. ``p_charge_max_kw > 0``、``p_discharge_max_kw > 0``
      3. ``0 <= soc_min < soc_max <= 1``
      4. ``soc_min <= soc_init <= soc_max``
      5. ``eta_charge``、``eta_discharge`` ∈ (0, 1]
      6. ``cycle_life > 0``、``capex_per_kwh >= 0``、``om_cost_per_kwh >= 0``

    Raises
    ------
    ValueError
        任一约束被违反时，消息中给出具体字段名与实际取值。
    """
    if not np.isfinite(params.capacity_kwh) or params.capacity_kwh <= 0.0:
        raise ValueError(
            "capacity_kwh 必须为正的有限值，实际为 {!r}".format(params.capacity_kwh)
        )
    if not np.isfinite(params.p_charge_max_kw) or params.p_charge_max_kw <= 0.0:
        raise ValueError(
            "p_charge_max_kw 必须为正的有限值，实际为 {!r}".format(params.p_charge_max_kw)
        )
    if not np.isfinite(params.p_discharge_max_kw) or params.p_discharge_max_kw <= 0.0:
        raise ValueError(
            "p_discharge_max_kw 必须为正的有限值，实际为 {!r}".format(
                params.p_discharge_max_kw
            )
        )
    if not (0.0 <= params.soc_min < params.soc_max <= 1.0):
        raise ValueError(
            "soc_min/soc_max 必须满足 0 <= soc_min < soc_max <= 1，"
            "实际为 soc_min={!r}, soc_max={!r}".format(params.soc_min, params.soc_max)
        )
    if not (params.soc_min - _SOC_TOL <= params.soc_init <= params.soc_max + _SOC_TOL):
        raise ValueError(
            "soc_init 必须落在 [soc_min, soc_max] 内，"
            "实际为 soc_init={!r}, soc_min={!r}, soc_max={!r}".format(
                params.soc_init, params.soc_min, params.soc_max
            )
        )
    for name in ("eta_charge", "eta_discharge"):
        eta = getattr(params, name)
        if not np.isfinite(eta) or not (0.0 < eta <= 1.0):
            raise ValueError(
                "{} 必须落在 (0, 1] 内，实际为 {!r}".format(name, eta)
            )
    if not np.isfinite(params.cycle_life) or params.cycle_life <= 0.0:
        raise ValueError(
            "cycle_life 必须为正的有限值，实际为 {!r}".format(params.cycle_life)
        )
    if not np.isfinite(params.capex_per_kwh) or params.capex_per_kwh < 0.0:
        raise ValueError(
            "capex_per_kwh 必须为非负的有限值，实际为 {!r}".format(params.capex_per_kwh)
        )
    if not np.isfinite(params.om_cost_per_kwh) or params.om_cost_per_kwh < 0.0:
        raise ValueError(
            "om_cost_per_kwh 必须为非负的有限值，实际为 {!r}".format(params.om_cost_per_kwh)
        )


def soc_bounds(params: BatteryParams) -> Tuple[float, float]:
    """返回 SOC 运行边界 ``(soc_min, soc_max)``。"""
    return (float(params.soc_min), float(params.soc_max))


def soc_energy_kwh(soc: float, params: BatteryParams) -> float:
    """给定 SOC 对应的电池内部可放电能量（kWh，相对 0% SOC）。"""
    return float(soc) * params.capacity_kwh


# --------------------------------------------------------------------------
# SOC 动力学
# --------------------------------------------------------------------------
def power_to_soc_delta(
    power_kw: float, params: BatteryParams, step_hours: float = STEP_HOURS
) -> float:
    """单步功率（kW，充正放负）引起的 SOC 增量（无量纲分位）。"""
    if power_kw >= 0.0:
        energy_kwh = params.eta_charge * power_kw * step_hours
    else:
        energy_kwh = power_kw * step_hours / params.eta_discharge
    return float(energy_kwh / params.capacity_kwh)


def simulate_soc(
    power_series_kw: np.ndarray,
    params: BatteryParams,
    step_hours: float = STEP_HOURS,
) -> np.ndarray:
    """开环仿真 SOC 轨迹（闭环校验钩子）。

    Parameters
    ----------
    power_series_kw : np.ndarray
        功率序列（kW），**正 = 充电，负 = 放电**。
    params : BatteryParams
        电池参数；函数内部会先调用 :func:`validate_params`。
    step_hours : float
        单步时长（小时），默认 0.25 h。

    Returns
    -------
    np.ndarray
        **每步结束时**的 SOC 数组，长度与输入一致；``soc[i]`` 表示
        ``power_series_kw[i]`` 执行完毕后的 SOC。起始 SOC 取 ``params.soc_init``。

    Raises
    ------
    ValueError
        参数非法；或轨迹越出 ``[soc_min, soc_max]``（说明调度解不可行）。

    Notes
    -----
    返回数组在数值上额外 clamp 到 ``[0, 1]`` 作为兜底保护，但真正的
    ``[soc_min, soc_max]`` 违约会显式抛错 —— 调用方（optimizer / simulate）
    依赖这一行为验证 LP 解与非线性电池模型的一致性。
    """
    validate_params(params)
    if step_hours <= 0.0:
        raise ValueError("step_hours 必须为正，实际为 {!r}".format(step_hours))

    power = np.asarray(power_series_kw, dtype=float)
    if power.ndim != 1:
        raise ValueError("power_series_kw 必须是一维序列，实际维度为 {}".format(power.ndim))
    if not np.all(np.isfinite(power)):
        raise ValueError("power_series_kw 含有 NaN/Inf，无法仿真")

    lo, hi = soc_bounds(params)
    soc = float(params.soc_init)
    out = np.empty(power.shape[0], dtype=float)

    for i, p in enumerate(power):
        soc = soc + power_to_soc_delta(float(p), params, step_hours)
        # 兜底 clamp，避免 1e-16 级浮点噪声传出 [0,1]
        soc = min(1.0, max(0.0, soc))
        if soc < lo - _SOC_TOL or soc > hi + _SOC_TOL:
            raise ValueError(
                "SOC 轨迹越界：step {} 结束时 soc={:.6f} 超出 [{}, {}]；"
                "功率序列在该步为 {:.3f} kW".format(i, soc, lo, hi, float(p))
            )
        out[i] = soc
    return out


# --------------------------------------------------------------------------
# 可持续功率能力
# --------------------------------------------------------------------------
def max_deliverable_kw(soc: float, params: BatteryParams, hours: float) -> float:
    """在 ``soc`` 状态下，可持续放电 ``hours`` 小时而不跌破 ``soc_min`` 的功率（kW，>=0）。

    由递推式反解：``(soc - soc_min) * capacity = P * hours / eta_discharge``
    ⇒ ``P = (soc - soc_min) * capacity * eta_discharge / hours``。
    结果再受 ``p_discharge_max_kw`` 限制；SOC 已到下限时返回 0。
    """
    if hours <= 0.0:
        raise ValueError("hours 必须为正，实际为 {!r}".format(hours))
    energy_internal_kwh = (float(soc) - params.soc_min) * params.capacity_kwh
    if energy_internal_kwh <= 0.0:
        return 0.0
    return float(
        min(params.p_discharge_max_kw, energy_internal_kwh * params.eta_discharge / hours)
    )


def max_absorbable_kw(soc: float, params: BatteryParams, hours: float) -> float:
    """在 ``soc`` 状态下，可持续充电 ``hours`` 小时而不超过 ``soc_max`` 的功率（kW，>=0）。

    与 :func:`max_deliverable_kw` 对称：``P = (soc_max - soc) * capacity / (eta_charge * hours)``。
    """
    if hours <= 0.0:
        raise ValueError("hours 必须为正，实际为 {!r}".format(hours))
    room_kwh = (params.soc_max - float(soc)) * params.capacity_kwh
    if room_kwh <= 0.0:
        return 0.0
    return float(
        min(params.p_charge_max_kw, room_kwh / (params.eta_charge * hours))
    )


# --------------------------------------------------------------------------
# 老化 / 度电成本
# --------------------------------------------------------------------------
def degradation_cost(throughput_kwh: float, params: BatteryParams) -> float:
    """放电吞吐量对应的电池老化成本（元）。

    推导（自洽定义）
    --------------
    1. 定义 **1 次等效全循环 = 累计放出 ``capacity_kwh`` 的电量**（放电侧计量）。
       之所以按放电侧而非「充+放」两侧计量，是因为放电量才是对负载的实际贡献，
       且避免充电侧效率损耗被重复计费。
    2. 全生命周期可放电吞吐量：``E_life = cycle_life * capacity_kwh`` (kWh)。
    3. 全生命周期投资：``C_life = capex_per_kwh * capacity_kwh`` (元)。
    4. 单位放电吞吐老化成本：
       ``c_deg = C_life / E_life = capex_per_kwh / cycle_life`` (元/kWh)。
    5. 再叠加运维成本 ``om_cost_per_kwh``，得到总度电成本
       ``c_total = c_deg + om_cost_per_kwh``（见 :func:`throughput_cost_per_kwh`）。

    Parameters
    ----------
    throughput_kwh : float
        放电吞吐量（kWh），负值表示无效输入。

    Returns
    -------
    float
        老化成本（元）；``throughput_kwh <= 0`` 时返回 ``0.0``。

    Notes
    -----
    该函数对吞吐量严格线性，是 LP 目标函数中电池项系数的来源
    （``throughput_cost_per_kwh``），保证优化问题仍为纯线性规划。
    """
    if not np.isfinite(throughput_kwh):
        raise ValueError("throughput_kwh 必须为有限值，实际为 {!r}".format(throughput_kwh))
    if throughput_kwh <= 0.0:
        return 0.0
    cost_per_kwh = params.capex_per_kwh / params.cycle_life + params.om_cost_per_kwh
    return float(cost_per_kwh * throughput_kwh)


def throughput_cost_per_kwh(params: BatteryParams) -> float:
    """单位放电吞吐综合成本（元/kWh）= 老化 + 运维，供 LP 目标函数线性使用。"""
    return float(params.capex_per_kwh / params.cycle_life + params.om_cost_per_kwh)
