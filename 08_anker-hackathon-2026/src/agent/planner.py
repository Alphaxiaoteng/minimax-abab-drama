"""Layer 3 · LLM 调度顾问。

PlannerAgent 只做一件事:把天气/电价/负荷/SOC 压成紧凑 JSON 交给 LLM,
产出策略意图 + 参数 + 中文解释;绝不生成设备指令。
所有参数落地前必过 core.policy.clamp_params/validate_params 护栏。
任何失败(不可用/坏 JSON/字段非法)→ 基于天气的确定性 rule_fallback。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from ..core.explain import explain_plan
from ..core.optimizer import PlanResult
from ..core.policy import GuardRails, PolicyParams, clamp_params, validate_params
from ..core.solar import WeatherForecast
from ..core.tariff import TariffPlan
from .llm import LLMClient, LLMError

VALID_MODES = ("arbitrage", "self_consumption", "resilience", "balanced")
_EPS = 1e-9

# rule_fallback 各模式的确定性参数
_FALLBACK: Dict[str, Dict[str, Any]] = {
    "arbitrage": dict(reserve_soc=0.10, target_soc=0.95, max_cycles_per_day=1.5,
                      risk_aversion=0.60, degradation_weight=0.25, allow_export=True),
    "self_consumption": dict(reserve_soc=0.10, target_soc=0.95, max_cycles_per_day=1.0,
                             risk_aversion=0.50, degradation_weight=0.40, allow_export=True),
    "resilience": dict(reserve_soc=0.50, target_soc=0.95, max_cycles_per_day=0.5,
                       risk_aversion=0.70, degradation_weight=0.50, allow_export=False),
    "balanced": dict(reserve_soc=0.20, target_soc=0.95, max_cycles_per_day=1.2,
                     risk_aversion=0.50, degradation_weight=0.35, allow_export=True),
}


@dataclass
class DailyPlan:
    params: PolicyParams
    rationale: List[str]
    source: str            # "llm" | "rule_fallback"
    raw: str = ""


_SYSTEM = (
    "你是 Anker 家用储能的能源调度顾问。你的唯一任务是生成次日调度「策略意图 + 参数 + 中文解释」。"
    "你绝不直接下发任何设备控制指令,实时执行与安全由下游 LP 优化器与 SafetyGuard 保证。"
    "运营安全边界由 GuardRails 在下游强制约束:请勿提出越界的 SOC、功率或循环数,越界值会被护栏收紧。"
    "你必须针对给出的真实数字逐条说明每个参数选择的依据(电价峰谷差、光伏出力、温度、当前 SOC、近期表现)。"
    "输出必须只含 JSON,不得有解释性前后缀、不得有 markdown 代码围栏。"
    "严格 JSON schema:{\"mode\": \"arbitrage|self_consumption|resilience|balanced\" 之一, "
    "\"reserve_soc\": float, \"target_soc\": float, \"max_cycles_per_day\": float, "
    "\"risk_aversion\": float(0激进~1保守), \"degradation_weight\": float, "
    "\"allow_export\": bool, \"rationale\": [3-5 条中文理由], \"confidence\": float(0~1)}"
)


def _as_float(v: Any, default: float) -> Tuple[float, bool]:
    """返回 (值, 是否解析成功)。"""
    if isinstance(v, bool):
        return default, False
    if isinstance(v, (int, float)):
        return float(v), True
    if isinstance(v, str):
        try:
            return float(v.strip()), True
        except (ValueError, TypeError):
            return default, False
    return default, False


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "是")
    if isinstance(v, (int, float)):
        return bool(v)
    return default


class PlannerAgent:
    def __init__(self, client: LLMClient, tariff: TariffPlan,
                 rails: Optional[GuardRails] = None) -> None:
        self.client = client
        self.tariff = tariff
        self.rails = rails or GuardRails()

    # ---- context 构建:紧凑,不倾倒 24 组原始数组 ----
    def _build_context(self, weather: WeatherForecast, load_kw: List[float],
                       soc: float, history: Optional[List[str]]) -> Dict[str, Any]:
        tiers = []
        for t in self.tariff.tiers:
            tiers.append({"name": t.name, "start": t.start_hour,
                          "end": t.end_hour, "price": t.price})
        precip = list(weather.precipitation or [])
        ctx = {
            "city": self.tariff.city,
            "tariff": {
                "export_price": self.tariff.export_price,
                "spread": round(self.tariff.spread(), 4),
                "tiers": tiers,
                "windows": {t.name: self.tariff.windows(t.name) for t in self.tariff.tiers},
            },
            "weather": {
                "ghi_peak_wm2": round(max(weather.ghi_wm2), 1) if weather.ghi_wm2 else 0.0,
                "cloud_mean": round(mean(weather.cloud_cover), 3) if weather.cloud_cover else 0.0,
                "temp_min_c": round(min(weather.temp_c), 1) if weather.temp_c else 0.0,
                "temp_max_c": round(max(weather.temp_c), 1) if weather.temp_c else 0.0,
                "precip_total_mm": round(sum(precip), 2) if precip else 0.0,
                "temp_c": [round(x, 1) for x in weather.temp_c],
                "cloud_cover": [round(x, 2) for x in weather.cloud_cover],
            },
            "load_kw_24h": [round(x, 3) for x in load_kw],
            "soc_now": round(soc, 3),
        }
        if history:
            ctx["recent_outcomes"] = list(history)[-6:]
        return ctx

    def _user_message(self, ctx: Dict[str, Any]) -> str:
        return ("以下是今日调度场景(单一 JSON 对象)。请基于其中的电价峰谷、光伏/温度、"
                "负荷曲线与当前 SOC,产出符合 schema 的调度策略 JSON:\n"
                + json.dumps(ctx, ensure_ascii=False))

    def plan(self, weather: WeatherForecast, load_kw: List[float],
             soc: float, history: Optional[List[str]] = None) -> DailyPlan:
        if not self.client.available:
            return self._fallback(weather,
                                  "LLM 不可用(%s):已启用基于天气的确定性回退" %
                                  (self.client.last_error or self.client.cfg.api_key_env))
        ctx = self._build_context(weather, load_kw, soc, history)
        messages = [{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": self._user_message(ctx)}]
        resp = self.client.chat_json(messages, max_tokens=900)
        if not resp:
            return self._fallback(weather,
                                  "LLM 未返回有效 JSON(%s):已启用基于天气的确定性回退" %
                                  (self.client.last_error or "空响应"))
        return self._from_llm(resp, weather)

    # ---- 解析 LLM JSON → clamp/validate → DailyPlan(source="llm") ----
    def _from_llm(self, resp: Dict[str, Any], weather: WeatherForecast) -> DailyPlan:
        rationale: List[str] = []
        raw_rat = resp.get("rationale")
        if isinstance(raw_rat, (list, tuple)):
            rationale.extend(str(x) for x in raw_rat)
        elif isinstance(raw_rat, str) and raw_rat.strip():
            rationale.append(raw_rat.strip())

        mode = str(resp.get("mode", "")).strip()
        if mode not in VALID_MODES:
            corrected = self._weather_mode(weather)[0]
            rationale.append("参数 mode 非法值 %r,已按天气画像替换为 %r" % (mode, corrected))
            mode = corrected

        default_pp = PolicyParams()
        reserve, ok_r = _as_float(resp.get("reserve_soc"), default_pp.reserve_soc)
        target, ok_t = _as_float(resp.get("target_soc"), default_pp.target_soc)
        cycles, ok_c = _as_float(resp.get("max_cycles_per_day"), default_pp.max_cycles_per_day)
        risk, ok_k = _as_float(resp.get("risk_aversion"), default_pp.risk_aversion)
        degw, ok_d = _as_float(resp.get("degradation_weight"), default_pp.degradation_weight)
        for name, ok in (("reserve_soc", ok_r), ("target_soc", ok_t),
                         ("max_cycles_per_day", ok_c), ("risk_aversion", ok_k),
                         ("degradation_weight", ok_d)):
            if not ok:
                rationale.append("参数 %s 非数值,已回退默认值" % name)

        pp = PolicyParams(
            mode=mode,
            reserve_soc=reserve,
            target_soc=target,
            max_cycles_per_day=cycles,
            risk_aversion=risk,
            degradation_weight=degw,
            allow_export=_as_bool(resp.get("allow_export"), default_pp.allow_export),
        )
        clamped = clamp_params(pp, self.rails)
        rationale.extend(self._clamp_notes(pp, clamped))
        for problem in validate_params(clamped):
            rationale.append("护栏校验:%s" % problem)
        conf = _as_float(resp.get("confidence"), 0.5)[0]
        if conf < 0.35:
            rationale.append("模型置信度较低(%.2f),建议下游采用保守回充窗口" % conf)

        return DailyPlan(params=clamped, rationale=rationale,
                         source="llm", raw=json.dumps(resp, ensure_ascii=False))

    @staticmethod
    def _clamp_notes(before: PolicyParams, after: PolicyParams) -> List[str]:
        notes: List[str] = []
        for attr in ("reserve_soc", "target_soc", "max_cycles_per_day",
                     "risk_aversion", "degradation_weight"):
            a = getattr(before, attr)
            b = getattr(after, attr)
            if abs(a - b) > _EPS:
                notes.append("参数 %s 被安全护栏从 %.4g 收紧至 %.4g" % (attr, a, b))
        return notes

    # ---- 天气→模式画像(也供 rule_fallback 复用) ----
    @staticmethod
    def _weather_mode(weather: WeatherForecast) -> Tuple[str, str]:
        cloud = mean(weather.cloud_cover) if weather.cloud_cover else 0.0
        temp_max = max(weather.temp_c) if weather.temp_c else 0.0
        ghi_peak = max(weather.ghi_wm2) if weather.ghi_wm2 else 0.0
        precip = sum(weather.precipitation) if weather.precipitation else 0.0
        if precip > 1.0 or cloud >= 0.6:
            return ("arbitrage",
                    "阴天/降雨(cloud=%.2f, precip=%.1f):光伏出力弱,套利优先——谷时买、峰时卖" % (cloud, precip))
        if cloud <= 0.2 and (temp_max >= 35.0 or ghi_peak >= 900.0):
            return ("self_consumption",
                    "晴热天(ghi_peak=%.0f, temp_max=%.1f, cloud=%.2f):光伏充足,优先自消纳并防高温降额" %
                    (ghi_peak, temp_max, cloud))
        return ("balanced",
                "温和天象(cloud=%.2f, ghi_peak=%.0f):平衡套利与自消纳" % (cloud, ghi_peak))

    def _fallback(self, weather: WeatherForecast, lead: str) -> DailyPlan:
        mode, why = self._weather_mode(weather)
        params = PolicyParams(mode=mode, **_FALLBACK[mode])
        params = clamp_params(params, self.rails)
        rationale = ["回退规则:%s" % lead, "模式判定:%s" % why]
        rationale.append("参数取 %s 模式默认值并经 GuardRails 收敛(reserve=%.2f, target=%.2f, cycles=%.1f)" %
                         (mode, params.reserve_soc, params.target_soc, params.max_cycles_per_day))
        return DailyPlan(params=params, rationale=rationale, source="rule_fallback", raw="")

    # ---- 自然语言解释 ----
    def explain(self, res: PlanResult) -> List[str]:
        if self.client.available:
            summary = self._plan_summary(res)
            messages = [
                {"role": "system", "content":
                    "你是储能调度播报员。请把下述数字结果改写成 3-5 句中文调度叙述,"
                    "面向家庭用户,突出省钱/自消纳/循环成本。只输出 JSON:"
                    "{\"narrative\": [\"句1\", \"句2\", ...]}"},
                {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
            ]
            parsed = self.client.chat_json(messages, max_tokens=600)
            narr = parsed.get("narrative") if isinstance(parsed, dict) else None
            if isinstance(narr, (list, tuple)) and narr:
                out = [str(x) for x in narr]
                if any(s.strip() for s in out):
                    return out
        base = explain_plan(res)
        if base:
            return list(base)
        return ["调度结果已生成:优化后电费 %.2f 元,节省 %.1f%%。" %
                (res.optimized_cost_cny, res.savings_pct * 100.0)]

    @staticmethod
    def _plan_summary(res: PlanResult) -> Dict[str, Any]:
        return {
            "site_id": res.site_id,
            "model": res.model,
            "mode": res.params.mode,
            "baseline_cost_cny": round(res.baseline_cost_cny, 2),
            "optimized_cost_cny": round(res.optimized_cost_cny, 2),
            "savings_cny": round(res.savings_cny, 2),
            "savings_pct": round(res.savings_pct, 3),
            "export_revenue_cny": round(res.export_revenue_cny, 2),
            "pv_self_consumption": round(res.pv_self_consumption, 3),
            "cycles_used": round(res.cycles_used, 2),
            "degradation_cost_cny": round(res.degradation_cost_cny, 2),
            "solver_status": res.solver_status,
            "rationale_head": list(res.rationale)[:3],
        }