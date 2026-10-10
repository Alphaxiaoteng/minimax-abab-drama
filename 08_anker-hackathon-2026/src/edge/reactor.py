"""Layer-1 规则反应器:断网/计划失效时的确定性兜底策略。

无随机、无网络:计划可用时透传;计划过期 (stale) 时按分时电价档位查规则表。
每个决策在返回前都必须过 SafetyGuard,反应器永不输出不安全功率。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core.battery import BatteryState
from core.policy import PolicyParams, clamp_params
from core.tariff import TariffPlan

from edge.safety import SafetyGuard


@dataclass
class ReactorDecision:
    power_kw: float
    source: str          # "plan"|"rule"|"safety"
    action: str
    reason: str


def _action_of(kw: float) -> str:
    if kw > 1e-9:
        return "charge"
    if kw < -1e-9:
        return "discharge"
    return "idle"


def _finite(x: float) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class RuleReactor:
    """离线可用的规则阶梯:plan → rule → safety。"""

    PEAK_TIERS = ("sharp_peak", "peak")
    VALLEY_TIERS = ("deep_valley", "valley")

    def __init__(self, tariff: TariffPlan, guard: SafetyGuard, params: PolicyParams) -> None:
        self.tariff = tariff
        self.guard = guard
        self.params = params

    @classmethod
    def from_preset(cls, tariff: TariffPlan, guard: SafetyGuard, mode: str = "arbitrage") -> "RuleReactor":
        """按模式快速构建 (默认策略参数,并经 rails 夹紧)。"""
        params = clamp_params(PolicyParams(mode=mode), guard.rails)
        return cls(tariff, guard, params)

    def decide(self, hour: float, soc: float, planned_kw: float,
               stale: bool = False) -> ReactorDecision:
        cfg = self.guard.cfg
        rails = self.guard.rails
        p_soc = float(soc) if _finite(soc) else cfg.soc_start

        if not stale and _finite(planned_kw):
            decision = ReactorDecision(
                power_kw=float(planned_kw), source="plan",
                action=_action_of(float(planned_kw)),
                reason="透传上游计划功率 %+.3f kW" % (float(planned_kw),))
        else:
            decision = self._rule(hour, p_soc, stale)

        return self._guard(hour, p_soc, decision)

    def _rule(self, hour: float, soc: float, stale: bool) -> ReactorDecision:
        cfg = self.guard.cfg
        rails = self.guard.rails
        tier = self.tariff.tier_at(hour)
        price = self.tariff.price_at(hour)
        capacity = max(1e-9, float(cfg.capacity_kwh))

        # 应急保底:尖峰 + 计划失效 + SOC 低于断电保底线 → 待机保电
        if stale and tier == "sharp_peak" and soc < rails.blackout_hold_soc:
            return ReactorDecision(
                power_kw=0.0, source="safety", action="hold",
                reason="尖峰时段但 soc=%.3f 低于断电保底线 %.3f,保持 0 kW 保底备电"
                       % (soc, rails.blackout_hold_soc))

        if tier in self.PEAK_TIERS and soc > self.params.reserve_soc + 0.05:
            want = -min(cfg.max_discharge_kw, (soc - self.params.reserve_soc) * capacity)
            return ReactorDecision(
                power_kw=want, source="rule", action="discharge",
                reason="%s 时段电价 %.3f 元/kWh,soc=%.3f 高于保底 %.3f,规则放电 %.3f kW"
                       % (tier, price, soc, self.params.reserve_soc, -want))

        if tier in self.VALLEY_TIERS and soc < self.params.target_soc:
            want = min(cfg.max_charge_kw, (self.params.target_soc - soc) * capacity)
            return ReactorDecision(
                power_kw=want, source="rule", action="charge",
                reason="%s 时段电价 %.3f 元/kWh,soc=%.3f 低于目标 %.3f,规则充电 %.3f kW"
                       % (tier, price, soc, self.params.target_soc, want))

        return ReactorDecision(
            power_kw=0.0, source="rule", action="idle",
            reason="非峰谷时段,保持待机")
