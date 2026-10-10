"""Layer-1 确定性硬保护 (SafetyGuard)。

最后防线:无论上游计划/规则给出什么功率,都必须先过这里。
纯标准库实现,无随机、无网络,可在边缘设备离线运行。
顺序:功率限幅 → 温度降额/停机 → SOC 下限 → SOC 上限 → 内部保底。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from core.battery import BatteryModel, BatteryState
from core.policy import GuardRails


@dataclass
class SafetyVerdict:
    allowed: bool
    clamped_kw: float
    reasons: List[str] = field(default_factory=list)


def _finite(x: float) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class SafetyGuard:
    """确定性安全护栏:把任意请求功率夹紧为安全功率。"""

    ABS_TEMP_C = 60.0  # 绝对停机温度

    def __init__(self, battery: BatteryModel, rails: Optional[GuardRails] = None) -> None:
        self.battery = battery
        self.cfg = battery.cfg
        self.rails = rails if rails is not None else GuardRails()

    def check(self, state: BatteryState, requested_kw: float,
              temp_c: float = 25.0, dt_hours: float = 1.0) -> SafetyVerdict:
        reasons: List[str] = []
        clamped = False
        cfg = self.cfg
        rails = self.rails

        p = requested_kw
        if not _finite(p):
            reasons.append(
                "非有限输入:请求功率 %r 为 NaN/无穷,已视为 0 kW" % (requested_kw,))
            p = 0.0
            clamped = True
        else:
            p = float(p)

        if not _finite(dt_hours) or float(dt_hours) <= 0:
            dt = 1.0
        else:
            dt = float(dt_hours)

        if not _finite(temp_c):
            temp_c = 25.0
        temp_c = float(temp_c)

        # --- 1. 功率硬限幅 (cfg 与 rails 取更严) ---
        upper = cfg.max_charge_kw
        if rails.max_charge_kw is not None:
            upper = min(upper, float(rails.max_charge_kw))
        lower = -cfg.max_discharge_kw
        if rails.max_discharge_kw is not None:
            lower = max(lower, -float(rails.max_discharge_kw))
        c = max(lower, min(upper, p))
        if abs(c - p) > 1e-9:
            reasons.append(
                "功率硬限幅:请求 %+.3f kW 超出安全区间 [%+.3f, %+.3f] kW,夹紧至 %+.3f kW"
                % (p, lower, upper, c))
            p = c
            clamped = True

        # --- 2. 温度降额 / 高温停机 ---
        if temp_c > self.ABS_TEMP_C:
            if abs(p) > 1e-9:
                reasons.append(
                    "电池温度 %.1f°C 超过绝对上限 %.1f°C,强制停机 0 kW(原 %+.3f kW)"
                    % (temp_c, self.ABS_TEMP_C, p))
            else:
                reasons.append(
                    "电池温度 %.1f°C 超过绝对上限 %.1f°C,维持停机 0 kW"
                    % (temp_c, self.ABS_TEMP_C))
            p = 0.0
            clamped = True
        elif temp_c > rails.temp_derate_c:
            factor = 1.0 - 0.5 * (temp_c - rails.temp_derate_c) / (self.ABS_TEMP_C - rails.temp_derate_c)
            factor = max(0.5, min(1.0, factor))
            d_upper = upper * factor
            d_lower = lower * factor
            c = max(d_lower, min(d_upper, p))
            reasons.append(
                "高温降额:温度 %.1f°C > 阈值 %.1f°C,可用功率降额至 %.0f%%,允许区间收敛为 [%+.3f, %+.3f] kW"
                % (temp_c, rails.temp_derate_c, factor * 100.0, d_lower, d_upper))
            if abs(c - p) > 1e-9:
                clamped = True
            p = c

        # --- 3. SOC 下限:本步放电不得使 SOC 低于 floor ---
        soc = float(state.soc) if state is not None else cfg.soc_start
        rte = max(0.01, min(1.0, float(cfg.round_trip_eff)))
        capacity = max(1e-9, float(cfg.capacity_kwh))

        floor = max(cfg.soc_min, float(rails.min_reserve_soc))
        if p < 0:
            d_max = (soc - floor) * capacity / (math.sqrt(rte) * dt)
            d_max = max(0.0, d_max)
            if -p > d_max + 1e-9:
                reasons.append(
                    "SOC 下限保护:当前 soc=%.3f,下限 %.3f,本步(%.2f h)最大放电 %.3f kW,请求 %.3f kW 已限幅"
                    % (soc, floor, dt, d_max, -p))
                p = -d_max
                clamped = True

        # --- 4. SOC 上限:充电不得使 SOC 超过 rails.max_soc ---
        ceiling = float(rails.max_soc)
        if p > 0:
            c_max = (ceiling - soc) * capacity / (math.sqrt(rte) * dt)
            c_max = max(0.0, c_max)
            if p > c_max + 1e-9:
                reasons.append(
                    "SOC 上限保护:当前 soc=%.3f,上限 %.3f,本步(%.2f h)最大充电 %.3f kW,请求 %.3f kW 已限幅"
                    % (soc, ceiling, c_max, p))
                p = c_max
                clamped = True

        # --- 5. 电池内部硬安全:不得低于 cfg.reserve_soc ---
        hard_floor = max(floor, float(cfg.reserve_soc))
        if hard_floor > floor and p < 0:
            d_max2 = (soc - hard_floor) * capacity / (math.sqrt(rte) * dt)
            d_max2 = max(0.0, d_max2)
            if -p > d_max2 + 1e-9:
                reasons.append(
                    "电池内部硬安全:不得低于 reserve_soc=%.3f(当前 soc=%.3f),本步最大放电 %.3f kW,已限幅"
                    % (cfg.reserve_soc, soc, d_max2))
                p = -d_max2
                clamped = True

        # 最终兜底:再次夹进功率窗口,并保证输出有限
        p = max(lower, min(upper, p))
        if not _finite(p):
            reasons.append("最终功率非有限,置 0 kW")
            p = 0.0
            clamped = True

        allowed = (not clamped) and not reasons
        return SafetyVerdict(allowed=allowed, clamped_kw=float(p), reasons=reasons)

    def emergency_stop(self, state: BatteryState, reason: str) -> SafetyVerdict:
        """故障/断电注入用的紧急停机:恒 0 kW,allowed=False。"""
        return SafetyVerdict(allowed=False, clamped_kw=0.0,
                             reasons=["紧急停机:%s" % (reason,)])