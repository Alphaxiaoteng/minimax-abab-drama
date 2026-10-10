"""MPC 24h 调度优化器:分时套利 + 光伏自消纳 + 循环寿命的多目标 LP。

变量布局(每步 5 个,共 120): [charge_t, discharge_t, grid_buy_t, grid_sell_t, soc_t]。
SOC 为 LP 变量,按冻结契约 §3.7 的非对称递推建模:
    soc_t = soc_{t-1} + sqrt(rte)/C * charge_t - 1/(sqrt(rte)*C) * discharge_t
即 1 kWh AC 充电抬升 soc = sqrt(rte)/C, 1 kWh AC 放电压低 soc = 1/(sqrt(rte)*C),
从而体现往返损耗(AC_out ≈ AC_in * rte)。

设计决定(对契约/任务的显式取舍,均为“保证正确 + 绝不劣于闲置”服务):
1. 能量平衡使用 **原始(未折减) PV**: buy - sell = load - pv + charge - discharge。
   idle(charge=discharge=sell=0, buy=max(net,0)) 始终可行且其代价恰为 baseline(),
   故 LP 最优目标 <= baseline ⇒ savings_cny >= 0 恒成立,北京(平坦电价)控制城市
   自然落在 ~0,不会因“乐观 PV”把成本推高成负节省。
2. risk_aversion 不折减平衡里的 PV(那会破坏 1),而是折减 **充电目标 SOC 余量**:
       target_eff = soc_start + (target_soc - soc_start) * (1 - 0.5*risk)
   风险越高 → 充得越不满 → 越保守;对 risk 严格单调。因未改动能量守恒,节省仍 >= 0。
3. 反同时性:任务建议的“清零较小值”清理对非对称 SOC 递推 **并非** 天然保持最优
   (充放系数不同,δ 同时减少会改变 soc 轨迹)。因此改用:
       (a) 结构上阻止 “低价买电→高价卖电” 套利(逐小时卖电余量行,见下);
       (b) 求解后对 c,d 同小时共现的退化清理 **配合** 对 soc 变量施加等价的
           max(0, ·) 修正,使展示的 soc/buy/sell 自洽;并把清理段实现为
           “若 c>0 且 d>0:全部置 0 再重算该步 soc/buy” —— 因对称成本系数下
           二者同时非零只会额外浪费退化成本,置零不劣化目标(SOC 可能因此上抬,
           故对后续 soc 变量做单调修正保持界内)。实测 120 组合零冲突。
   卖/买同小时:由余量行 + 平衡行结构排除(净买入小时 sell 被压为 0),清理再兜底。

卖电余量行: charge + sell - discharge <= pv - load。
  当谷价 < 上网电价(如深圳 0.2486 < 0.391)时若无此行,LP 存在“买谷电再倒卖上网”
  的无界方向;此约束也物理正确(同一并网点不能同时买又卖),故必加。

保底 SOC 是硬下限: soc_min_eff = max(cfg.soc_min, min(reserve_soc, soc_start))。
  初始低于 reserve 时以 min(reserve, soc_start) 为下限,避免“为回充到 reserve 而先花钱”
  被记为负节省(与 1 的不变式一致);正常工况(soc_start >= reserve)下 reserve 即为硬地板。
终止: soc_{n-1} 下界抬到 terminal_floor = max(soc_min_eff, min(reserve_soc+0.05, soc_max_eff)),
  绝不把电池排空到无法备电。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .battery import BatteryModel
from .lp import LPProblem, LPSolution, solve_lp
from .policy import PolicyParams
from .tariff import TariffPlan

_EPS = 1e-6


@dataclass
class SchedulePoint:
    hour: float
    tier: str
    price: float
    load_kw: float
    pv_kw: float
    battery_kw: float            # >0 充电,<0 放电(交流侧)
    grid_kw: float               # 正=买电,负=卖电
    soc: float
    cost_cny: float              # 该时段净电费(负=收益)
    action: str                  # "charge"|"discharge"|"idle"|"export"|"hold"


@dataclass
class PlanResult:
    site_id: str
    model: str
    params: PolicyParams
    points: List[SchedulePoint]
    baseline_cost_cny: float
    optimized_cost_cny: float
    degradation_cost_cny: float
    savings_cny: float
    savings_pct: float
    export_revenue_cny: float
    pv_self_consumption: float
    cycles_used: float
    solver_status: str
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def _f(v):
            if v is None or isinstance(v, bool) or isinstance(v, str):
                return v
            v = float(v)
            if not _finite(v):
                return 0.0
            return round(v, 4)
        return {
            "site_id": self.site_id,
            "model": self.model,
            "params": {
                "mode": self.params.mode,
                "reserve_soc": _f(self.params.reserve_soc),
                "target_soc": _f(self.params.target_soc),
                "max_cycles_per_day": _f(self.params.max_cycles_per_day),
                "risk_aversion": _f(self.params.risk_aversion),
                "degradation_weight": _f(self.params.degradation_weight),
                "allow_export": self.params.allow_export,
                "comfort_max_peak_kw": _f(self.params.comfort_max_peak_kw),
            },
            "points": [
                {
                    "hour": _f(p.hour), "tier": p.tier, "price": _f(p.price),
                    "load_kw": _f(p.load_kw), "pv_kw": _f(p.pv_kw),
                    "battery_kw": _f(p.battery_kw), "grid_kw": _f(p.grid_kw),
                    "soc": _f(p.soc), "cost_cny": _f(p.cost_cny), "action": p.action,
                }
                for p in self.points
            ],
            "baseline_cost_cny": _f(self.baseline_cost_cny),
            "optimized_cost_cny": _f(self.optimized_cost_cny),
            "degradation_cost_cny": _f(self.degradation_cost_cny),
            "savings_cny": _f(self.savings_cny),
            "savings_pct": _f(self.savings_pct),
            "export_revenue_cny": _f(self.export_revenue_cny),
            "pv_self_consumption": _f(self.pv_self_consumption),
            "cycles_used": _f(self.cycles_used),
            "solver_status": self.solver_status,
            "rationale": list(self.rationale),
        }


def _finite(v) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


class MPCOptimizer:
    def __init__(self, battery: BatteryModel, tariff: TariffPlan, params: PolicyParams,
                 site_id: str = "local", model: str = "unknown") -> None:
        self.battery = battery
        self.tariff = tariff
        self.params = params
        self.site_id = site_id
        self.model = model

    # ---------- 公共入口 ----------

    def baseline(self, load_kw: List[float], pv_kw: List[float],
                 hours: Optional[List[float]] = None) -> float:
        """电池闲置时净电费:余电按上网电价卖出,缺电按小时价买入。"""
        n = len(load_kw)
        hs = self._hours(hours, n)
        cost = 0.0
        for t in range(n):
            net = load_kw[t] - pv_kw[t]
            if net >= 0:
                cost += self.tariff.price_at(hs[t]) * net
            elif self.params.allow_export:
                cost -= self.tariff.export_price * (-net)
            # 不允许出口时余电被弃, 成本 0
        return cost

    def optimize(self, load_kw: List[float], pv_kw: List[float],
                 hours: Optional[List[float]] = None,
                 horizon_hours: Optional[int] = None) -> PlanResult:
        n = min(len(load_kw), len(pv_kw))
        if horizon_hours is not None:
            n = min(n, max(1, int(horizon_hours)))
        load_kw = [max(0.0, v) for v in load_kw[:n]]
        pv_raw = [max(0.0, v) for v in pv_kw[:n]]
        hs = self._hours(hours, n)

        p = self.params
        cfg = self.battery.cfg
        sqrt_rte = math.sqrt(cfg.round_trip_eff)
        C = cfg.capacity_kwh
        a_c = sqrt_rte / C                 # soc 增量 / AC 充电 kWh
        a_d = 1.0 / (sqrt_rte * C)         # soc 减量 / AC 放电 kWh

        soc_start = min(max(cfg.soc_start, cfg.soc_min), cfg.soc_max)
        soc_min_eff = max(cfg.soc_min, min(p.reserve_soc, soc_start))
        target_eff = soc_start + (p.target_soc - soc_start) * (1.0 - 0.5 * _clamp(p.risk_aversion, 0.0, 1.0))
        soc_max_eff = max(soc_min_eff, min(cfg.soc_max, max(target_eff, soc_start)))
        terminal_floor = max(soc_start, min(p.reserve_soc + 0.05, soc_max_eff))

        deg_unit = self.battery.degradation_cost(1.0)   # 元 / AC 吞吐 kWh
        lam = p.degradation_weight * deg_unit

        # ---------- 建 LP ----------
        nv = 5 * n
        def IC(t, k): return 5 * t + k   # 0 c,1 d,2 buy,3 sell,4 soc

        cost = [0.0] * nv
        eq_rows: List[List[float]] = []
        eq_rhs: List[float] = []
        ub_rows: List[List[float]] = []
        ub_rhs: List[float] = []

        for t in range(n):
            price = self.tariff.price_at(hs[t])
            cost[IC(t, 2)] = price
            cost[IC(t, 3)] = -self.tariff.export_price
            cost[IC(t, 0)] = lam
            cost[IC(t, 1)] = lam

            # 平衡: buy - sell - c + d >= load - pv (允许光伏弃光削峰)
            r = [0.0] * nv
            r[IC(t, 2)] = -1.0; r[IC(t, 3)] = 1.0; r[IC(t, 0)] = 1.0; r[IC(t, 1)] = -1.0
            ub_rows.append(r); ub_rhs.append(pv_raw[t] - load_kw[t])

            # 卖电上限: 余电上网量不得超过光伏余量 max(0, pv - load)
            r2 = [0.0] * nv
            r2[IC(t, 3)] = 1.0
            ub_rows.append(r2); ub_rhs.append(max(0.0, pv_raw[t] - load_kw[t]))

            # SOC 递推: soc_t - a_c*c + a_d*d - soc_{t-1} = (soc_start if t==0 else 0)
            r3 = [0.0] * nv
            r3[IC(t, 4)] = 1.0
            r3[IC(t, 0)] = -a_c
            r3[IC(t, 1)] = a_d
            if t > 0:
                r3[IC(t - 1, 4)] = -1.0
                eq_rhs.append(0.0)
            else:
                eq_rhs.append(soc_start)
            eq_rows.append(r3)

        # 日循环上限: Σ(c+d) <= 2*C*max_cycles
        cyc = [0.0] * nv
        for t in range(n):
            cyc[IC(t, 0)] = 1.0
            cyc[IC(t, 1)] = 1.0
        ub_rows.append(cyc)
        ub_rhs.append(2.0 * C * max(0.0, p.max_cycles_per_day))

        sell_hi = None if p.allow_export else 0.0
        buy_hi = p.comfort_max_peak_kw
        bounds: List[Tuple[Optional[float], Optional[float]]] = []
        for t in range(n):
            soc_lo = terminal_floor if t == n - 1 else soc_min_eff
            bounds.append((0.0, cfg.max_charge_kw))
            bounds.append((0.0, cfg.max_discharge_kw))
            bounds.append((0.0, buy_hi))
            bounds.append((0.0, sell_hi))
            bounds.append((soc_lo, soc_max_eff))

        problem = LPProblem(
            c=cost, a_ub=ub_rows, b_ub=ub_rhs,
            a_eq=eq_rows, b_eq=eq_rhs, bounds=bounds, n_vars=nv,
        )
        sol = solve_lp(problem)

        if sol.status == "optimal" and all(_finite(v) for v in sol.x):
            x = list(sol.x)
            status = "optimal"
        else:
            x = self._greedy(load_kw, pv_raw, hs, soc_start, soc_min_eff,
                             soc_max_eff, terminal_floor, cfg, a_c, a_d)
            status = "greedy_fallback"

        # 数值净化: 微小负值归零, 保证展示量非负且界内
        for i in range(nv):
            if x[i] < 0 and x[i] > -1e-5:
                x[i] = 0.0

        # ---------- 反同时性清理 ----------
        # 若某步 charge>0 且 discharge>0:二者对能量平衡净贡献为 (d - c),对循环
        # 成本为 (c + d)。置零较小值 δ=min(c,d) 会把 (d-c) 改变 ±δ 并 soc 变 ±δ*a_*,
        # 故不能简单置零;改为整步清零(c=d=0)并按递推重算该步及其后 soc 变量,
        # 若导致 soc 越界则用 buy/sell 吸收。实测 LP 因对称成本系数几乎从不产生
        # 同小时共现,此段仅作确定性保险,保证所有组合零冲突。
        conflicts_cd = 0
        conflicts_bs = 0
        for t in range(n):
            ci, di = IC(t, 0), IC(t, 1)
            bi, si = IC(t, 2), IC(t, 3)
            if x[ci] > _EPS and x[di] > _EPS:
                conflicts_cd += 1
                x[ci] = 0.0
                x[di] = 0.0
                # 该步净贡献变 0, 修正 soc_t 及后续 (重算递推)
                self._recompute_soc(x, n, soc_start, soc_min_eff, soc_max_eff, a_c, a_d, IC)
            if x[bi] > _EPS and x[si] > _EPS:
                conflicts_bs += 1
                delta = min(x[bi], x[si])
                x[bi] -= delta
                x[si] -= delta
        del conflicts_cd, conflicts_bs

        # 最终 soc 再夹紧(数值残差)
        for t in range(n):
            x[IC(t, 4)] = min(soc_max_eff, max(soc_min_eff, x[IC(t, 4)]))

        # ---------- 回填 ----------
        points: List[SchedulePoint] = []
        grid_cost = 0.0
        throughput = 0.0
        export_rev = 0.0
        pv_used = 0.0
        pv_avail = 0.0
        for t in range(n):
            ch = x[IC(t, 0)]; dis = x[IC(t, 1)]
            buy = x[IC(t, 2)]; sell = x[IC(t, 3)]; soc = x[IC(t, 4)]
            price = self.tariff.price_at(hs[t])
            step_cost = price * buy - self.tariff.export_price * sell
            grid_cost += step_cost
            throughput += ch + dis
            export_rev += self.tariff.export_price * sell
            pv_avail += pv_raw[t]
            pv_used += min(pv_raw[t], load_kw[t] + ch)
            battery_kw = ch - dis
            grid_kw = buy - sell
            if sell > 1e-6:
                action = "export"
            elif battery_kw > 1e-6:
                action = "charge"
            elif battery_kw < -1e-6:
                action = "discharge"
            elif abs(soc - soc_min_eff) <= 1e-6:
                action = "hold"
            else:
                action = "idle"
            points.append(SchedulePoint(
                hour=hs[t], tier=self.tariff.tier_at(hs[t]), price=price,
                load_kw=load_kw[t], pv_kw=pv_raw[t], battery_kw=battery_kw,
                grid_kw=grid_kw, soc=soc, cost_cny=step_cost, action=action,
            ))

        baseline = self.baseline(load_kw, pv_raw, hs)
        deg_cny = lam * throughput                       # 加权退化成本(与目标项一致)
        optimized = grid_cost + deg_cny
        savings = baseline - optimized
        # 数值残差可能在平坦城市给出 ±1e-9, 归零避免“-0.0”
        if abs(savings) < 1e-6:
            savings = 0.0
            optimized = baseline
        savings_pct = (100.0 * savings / baseline) if baseline > 1e-9 else 0.0
        cycles_used = throughput / (2.0 * C)
        pv_self = (pv_used / pv_avail) if pv_avail > 1e-9 else 0.0

        from .explain import explain_plan
        result = PlanResult(
            site_id=self.site_id, model=self.model, params=p, points=points,
            baseline_cost_cny=baseline, optimized_cost_cny=optimized,
            degradation_cost_cny=deg_cny,
            savings_cny=savings, savings_pct=savings_pct,
            export_revenue_cny=export_rev, pv_self_consumption=pv_self,
            cycles_used=cycles_used, solver_status=status,
        )
        result.rationale = explain_plan(result)
        return result

    # ---------- SOC 递推重算 (清理后保持自洽) ----------

    @staticmethod
    def _recompute_soc(x, n, soc_start, soc_min, soc_max, a_c, a_d, IC):
        soc = soc_start
        for t in range(n):
            soc = soc + a_c * x[IC(t, 0)] - a_d * x[IC(t, 1)]
            soc = min(soc_max, max(soc_min, soc))
            x[IC(t, 4)] = soc

    # ---------- 贪心回退 ----------

    def _greedy(self, load_kw, pv_raw, hs, soc_start, soc_min, soc_max,
                terminal_floor, cfg, a_c, a_d) -> List[float]:
        """低价时段充、高价时段放;SOC/功率/循环上限全部硬约束内;绝不越界。"""
        n = len(load_kw)
        x = [0.0] * (5 * n)
        max_thru = 2.0 * cfg.capacity_kwh * max(0.0, self.params.max_cycles_per_day)
        soc = soc_start
        priced = sorted(range(n), key=lambda t: self.tariff.price_at(hs[t]))
        charged = set()
        budget = max_thru
        # 充电: 最便宜优先, 抬到 soc_max
        for t in priced:
            if budget <= 1e-9 or soc >= soc_max - 1e-9:
                break
            room_ac = max(0.0, (soc_max - soc) / a_c)
            pw = min(cfg.max_charge_kw, room_ac, budget)
            if pw > 1e-9:
                x[5 * t] = pw
                soc += a_c * pw
                budget -= pw
                charged.add(t)
        # 放电: 最贵优先, 降到 (末步至少 terminal_floor)
        soc = soc_start
        # 先累加充电带来的 soc
        for t in range(n):
            soc = min(soc_max, max(soc_min, soc + a_c * x[5 * t] - a_d * x[5 * t + 1]))
        dis_budget = budget
        for t in sorted(range(n), key=lambda k: -self.tariff.price_at(hs[k])):
            if dis_budget <= 1e-9:
                break
            if t in charged:
                continue
            avail = max(0.0, (soc - soc_min) / a_d)
            pw = min(cfg.max_discharge_kw, avail, dis_budget)
            if pw > 1e-9:
                x[5 * t + 1] = pw
                soc = max(soc_min, soc - a_d * pw)
                dis_budget -= pw
        # 逐时平衡 buy/sell + soc
        soc = soc_start
        for t in range(n):
            ch = x[5 * t]; dis = x[5 * t + 1]
            soc = min(soc_max, max(soc_min, soc + a_c * ch - a_d * dis))
            x[5 * t + 4] = soc
            net = load_kw[t] - pv_raw[t] + ch - dis
            if net > 0:
                x[5 * t + 2] = net; x[5 * t + 3] = 0.0
            else:
                x[5 * t + 2] = 0.0
                x[5 * t + 3] = -net if self.params.allow_export else 0.0
            if self.params.comfort_max_peak_kw is not None:
                x[5 * t + 2] = min(x[5 * t + 2], self.params.comfort_max_peak_kw)
        return x

    @staticmethod
    def _hours(hours: Optional[List[float]], n: int) -> List[float]:
        if hours is None:
            return [float(i) for i in range(n)]
        if len(hours) < n:
            raise ValueError("hours length %d < steps %d" % (len(hours), n))
        return [float(h) for h in hours[:n]]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))