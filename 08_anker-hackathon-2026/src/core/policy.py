"""策略参数与安全护栏: PolicyParams / GuardRails / clamp/validate / 模式预设。

四个模式(arbitrage/self_consumption/resilience/balanced)提供差异化默认值;
clamp_params 保证 SOC 与功率边界物理可行, validate_params 返回中文可读问题列表。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

KNOWN_MODES = ("arbitrage", "self_consumption", "resilience", "balanced")


@dataclass
class PolicyParams:
    mode: str = "arbitrage"                                # 4 种已知模式
    reserve_soc: float = 0.10
    target_soc: float = 0.95
    max_cycles_per_day: float = 1.2
    risk_aversion: float = 0.5                             # 0=激进 1=保守
    degradation_weight: float = 0.35
    allow_export: bool = True
    comfort_max_peak_kw: Optional[float] = None


@dataclass
class GuardRails:
    min_reserve_soc: float = 0.10
    max_soc: float = 0.98
    max_charge_kw: Optional[float] = None
    max_discharge_kw: Optional[float] = None
    blackout_hold_soc: float = 0.50
    temp_derate_c: float = 45.0


def clamp_params(p: PolicyParams, rails: GuardRails) -> PolicyParams:
    """将参数强制夹到 rails 允许的区间。返回新对象,不改入参。

    规则(按顺序应用):
      1. mode 不在 KNOWN_MODES -> 回退 "balanced" 并记入 issues。
      2. risk_aversion 夹到 [0, 1]; degradation_weight 夹到 [0, 2]。
      3. reserve_soc 不低于 rails.min_reserve_soc。
      4. target_soc 不高于 rails.max_soc, 不低于 0.5。
      5. 若 reserve >= target (SOC 死区): 保留 target 不动, 把 reserve
         下调至 target - 0.05 再兜底 min_reserve_soc。若这样仍冲突,
         说明 target 太小, 转而提升 target = min(rails.max_soc, reserve + 0.05)。
      6. comfort_max_peak_kw 保留;None 表示无硬顶。
    """
    issues: List[str] = []
    mode = p.mode if p.mode in KNOWN_MODES else "balanced"
    if mode != p.mode:
        issues.append("mode=%r 非法, 回退 balanced" % (p.mode,))

    risk = min(1.0, max(0.0, p.risk_aversion))
    wdeg = min(2.0, max(0.0, p.degradation_weight))

    reserve = max(rails.min_reserve_soc, p.reserve_soc)
    target = min(rails.max_soc, max(0.5, p.target_soc))

    if reserve >= target:
        # 优先保留 target 不动, 降低 reserve
        new_reserve = max(rails.min_reserve_soc, target - 0.05)
        if new_reserve >= target:
            # target 太小, 抬高 target
            target = min(rails.max_soc, reserve + 0.05)
            new_reserve = max(rails.min_reserve_soc, min(reserve, target - 0.05))
        reserve = new_reserve
        issues.append("reserve>=target, 已自动分离 (reserve=%.2f target=%.2f)" % (reserve, target))

    return PolicyParams(
        mode=mode,
        reserve_soc=round(reserve, 6),
        target_soc=round(target, 6),
        max_cycles_per_day=max(0.0, p.max_cycles_per_day),
        risk_aversion=round(risk, 6),
        degradation_weight=round(wdeg, 6),
        allow_export=bool(p.allow_export),
        comfort_max_peak_kw=p.comfort_max_peak_kw,
    )


def validate_params(p: PolicyParams) -> List[str]:
    """人类可读中文问题列表;空表示无问题。仅检查,不改动。"""
    issues: List[str] = []
    if p.mode not in KNOWN_MODES:
        issues.append("模式 %r 未知, 应属于 %s" % (p.mode, "/".join(KNOWN_MODES)))
    if not (0.0 <= p.reserve_soc <= 1.0):
        issues.append("保底 SOC %.3f 超出 [0,1]" % p.reserve_soc)
    if not (0.0 <= p.target_soc <= 1.0):
        issues.append("目标 SOC %.3f 超出 [0,1]" % p.target_soc)
    if p.reserve_soc >= p.target_soc:
        issues.append("保底 SOC %.3f 应严格小于目标 SOC %.3f (否则无可用调节区间)" % (p.reserve_soc, p.target_soc))
    if not (0.0 <= p.risk_aversion <= 1.0):
        issues.append("风险厌恶 %.3f 应在 [0,1]" % p.risk_aversion)
    if not (0.0 <= p.degradation_weight <= 2.0):
        issues.append("退化成本权重 %.3f 应在 [0,2]" % p.degradation_weight)
    if p.max_cycles_per_day <= 0.0:
        issues.append("日循环上限 %.3f 必须为正" % p.max_cycles_per_day)
    if p.max_cycles_per_day > 4.0:
        issues.append("日循环上限 %.3f 偏高, 可能加速电池衰减" % p.max_cycles_per_day)
    if p.comfort_max_peak_kw is not None and p.comfort_max_peak_kw <= 0.0:
        issues.append("舒适功率上限 %.3f kW 若设定必须为正" % p.comfort_max_peak_kw)
    return issues


def mode_presets() -> Dict[str, PolicyParams]:
    """四种模式的分层默认策略 (差异化设计:套利/自消纳/备电/均衡)。"""
    return {
        "arbitrage": PolicyParams(
            mode="arbitrage",
            reserve_soc=0.10,
            target_soc=0.95,
            max_cycles_per_day=1.5,
            risk_aversion=0.4,
            degradation_weight=0.20,
            allow_export=True,
            comfort_max_peak_kw=None,
        ),
        "self_consumption": PolicyParams(
            mode="self_consumption",
            reserve_soc=0.15,
            target_soc=0.90,
            max_cycles_per_day=1.0,
            risk_aversion=0.5,
            degradation_weight=0.30,
            allow_export=False,
            comfort_max_peak_kw=None,
        ),
        "resilience": PolicyParams(
            mode="resilience",
            reserve_soc=0.50,
            target_soc=0.80,
            max_cycles_per_day=0.8,
            risk_aversion=0.7,
            degradation_weight=0.40,
            allow_export=False,
            comfort_max_peak_kw=None,
        ),
        "balanced": PolicyParams(
            mode="balanced",
            reserve_soc=0.20,
            target_soc=0.92,
            max_cycles_per_day=1.2,
            risk_aversion=0.5,
            degradation_weight=0.35,
            allow_export=True,
            comfort_max_peak_kw=None,
        ),
    }