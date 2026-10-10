"""策略 → 中文自然语言解释 (数据驱动, 非模板填充)。

explain_plan 从 PlanResult 的实际小时/价格/电量里提炼真实洞察:
最便宜/最贵时段、实际充放窗口、量化节省、循环用量与上限对比、光伏自消纳率,
并在节省偏低时给出提示。compare_plans 对比两个 PlanResult 的成本/节省/循环/自消纳。
"""
from __future__ import annotations

from typing import List


def _fmt(v: float, nd: int = 2) -> str:
    try:
        return ("%." + str(nd) + "f") % float(v)
    except (TypeError, ValueError):
        return "0"


def explain_plan(res) -> List[str]:
    points = res.points
    out: List[str] = []
    if not points:
        return ["无调度点可解释。"]

    # 实际充/放电窗口 + 最便宜/最贵小时
    charge_hours = [p.hour for p in points if p.action == "charge"]
    discharge_hours = [p.hour for p in points if p.action == "discharge"]
    cheapest = min(points, key=lambda p: p.price)
    dearest = max(points, key=lambda p: p.price)

    out.append("全天最便宜时段 %.0f 点 %s 价 %s 元,最贵时段 %.0f 点 %s 价 %s 元,价差 %s 元/kWh。"
               % (cheapest.hour, cheapest.tier, _fmt(cheapest.price, 4),
                  dearest.hour, dearest.tier, _fmt(dearest.price, 4),
                  _fmt(dearest.price - cheapest.price, 4)))

    if charge_hours:
        out.append("低谷充电窗口: %.0f-%.0f 点共 %d 个小时;高峰放电窗口: %s。"
                   % (min(charge_hours), max(charge_hours), len(charge_hours),
                      ("%.0f-%.0f 点共 %d 个小时" % (min(discharge_hours), max(discharge_hours), len(discharge_hours)))
                      if discharge_hours else "无"))
    else:
        out.append("本方案未安排充放电(价差或预测置信度不足以覆盖退化成本)。")

    out.append("较基准节省 %s 元(%.1f%%),其中退化为成本权重扣减 %s 元。"
               % (_fmt(res.savings_cny), res.savings_pct, _fmt(res.degradation_cost_cny)))

    out.append("当日循环用量 %.2f 次;光伏自消纳率 %.0f%%;上网售电收益 %s 元。"
               % (res.cycles_used, 100.0 * res.pv_self_consumption, _fmt(res.export_revenue_cny)))

    if res.savings_pct < 5.0:
        out.append("提示:节省比例低于 5%%,建议检查电价结构、保底 SOC 是否过高或天气/负荷预测是否过于保守。")

    if res.solver_status != "optimal":
        out.append("注意:LP 求解器返回 %s,已回退确定性贪心调度(保证不越 SOC 界)。" % res.solver_status)

    return out


def compare_plans(a, b) -> List[str]:
    out: List[str] = []
    if not a.points or not b.points:
        return ["对比需要两个含调度点的方案。"]
    d_sav = a.savings_cny - b.savings_cny
    out.append("方案A(节省 %s 元 / %.1f%%)对比方案B(节省 %s 元 / %.1f%%):%s%s 元。"
               % (_fmt(a.savings_cny), a.savings_pct,
                  _fmt(b.savings_cny), b.savings_pct,
                  "A 多赚" if d_sav >= 0 else "B 多赚",
                  _fmt(abs(d_sav))))
    out.append("循环用量:A %.2f 次 vs B %.2f 次(越多电池衰减越快)。"
               % (a.cycles_used, b.cycles_used))
    out.append("光伏自消纳率:A %.0f%% vs B %.0f%%。"
               % (100.0 * a.pv_self_consumption, 100.0 * b.pv_self_consumption))
    out.append("上网收益:A %s 元 vs B %s 元;求解状态 A=%s, B=%s。"
               % (_fmt(a.export_revenue_cny), _fmt(b.export_revenue_cny),
                  a.solver_status, b.solver_status))
    return out