"""CLI 入口 —— 运行仿真并生成报告。

用法
----
    python -m src.main --all                      # 全部情景 + 报告
    python -m src.main --scenario transient_spike # 单个情景
    python -m src.main --all --no-charts          # 跳过绘图（无 matplotlib 环境）
    python -m src.main --all --reserve 200        # 预留 200 kW 并网点容量（N-1）
    python -m src.main --list                     # 列出可用情景
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional

import numpy as np

from src.config import default_scenarios, scenario_by_name
from src.report import write_report
from src.simulate import SimulationResult, run_scenario

_DEFAULT_OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def _print_result(res: SimulationResult) -> None:
    """控制台摘要表。"""
    cmp_ = res.comparison()
    print("")
    print("=" * 78)
    print("情景: {}  —— {}".format(res.scenario.name, res.scenario.description))
    print("=" * 78)
    print("{:<16}{:>14}{:>14}{:>14}{:>10}".format(
        "策略", "综合成本(元)", "电网峰值(kW)", "削峰比例", "负荷率"))
    print("-" * 78)
    for name in ("baseline", "greedy", "optimal"):
        if name not in res.kpis:
            continue
        k = res.kpis[name]
        label = {"baseline": "无储能", "greedy": "规则定时充放", "optimal": "LP 最优"}[name]
        print("{:<16}{:>14,.1f}{:>14,.1f}{:>13.2%}{:>10.3f}".format(
            label, k["total_cost"], k["peak_grid_kw"], k["peak_shaved_ratio"], k["load_factor"]))
    print("-" * 78)
    print("节省: {:,.1f} 元/日 ({:.2f}%)   LP vs 规则: {:,.1f} 元/日 ({:.2f}%)".format(
        cmp_["cost_saving_yuan"], cmp_["cost_saving_pct"],
        cmp_["lp_vs_greedy_yuan"], cmp_["lp_vs_greedy_pct"]))
    print("削峰: {:,.1f} kW ({:.2f}%)    购电量变化: {:,.1f} kWh/日 (储能损耗所致)".format(
        cmp_["peak_shaved_kw"], cmp_["peak_shaved_pct"],
        res.kpis["optimal"]["saved_energy_kwh"]))
    print("PUE: 均值 {:.4f} / P95 {:.4f} / 最大 {:.4f}".format(
        res.pue_stats["baseline"]["avg"],
        res.pue_stats["baseline"]["quantiles"].get("p95", float("nan")),
        res.pue_stats["baseline"]["max"]))
    print("IT 峰值 {:.0f} kW（基线 {:.0f} kW），瞬态尖峰 {} 次，"
          "尖峰能量 {:,.0f} kWh，尖峰占空比 {:.1%}".format(
              float(np.max(res.it_power)),
              res.scenario.datacenter.it_base_kw,
              int(res.load_stats.get("spike_events", 0)),
              float(res.load_stats.get("transient_energy_kwh", 0.0)),
              float(res.load_stats.get("duty", 0.0))))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.main",
        description="钠电储能 × AIDC 瞬态算力削峰填谷 —— 线性规划仿真与 PUE 分析",
    )
    p.add_argument("--scenario", default=None,
                   help="只跑指定情景（见 --list）")
    p.add_argument("--all", action="store_true",
                   help="跑全部默认情景（默认行为）")
    p.add_argument("--list", action="store_true", help="列出可用情景后退出")
    p.add_argument("--seed", type=int, default=None, help="覆盖情景随机种子")
    p.add_argument("--reserve", type=float, default=0.0,
                   help="并网点预留容量 (kW)，用于 N-1 校验")
    p.add_argument("--outdir", default=_DEFAULT_OUTDIR, help="报告输出目录")
    p.add_argument("--no-charts", action="store_true", help="跳过 PNG 绘图")
    p.add_argument("--no-greedy", action="store_true", help="不做规则策略对照")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        for s in default_scenarios():
            print("{:<18} 电池 {:>8.0f} kWh / {:>6.0f} kW   {}".format(
                s.name, s.battery.capacity_kwh, s.battery.p_discharge_max_kw, s.description))
        return 0

    if args.scenario:
        scenarios = [scenario_by_name(args.scenario)]
    else:
        scenarios = default_scenarios()

    if args.seed is not None:
        for s in scenarios:
            s.seed = args.seed

    results: List[SimulationResult] = []
    t0 = time.time()
    for sc in scenarios:
        try:
            res = run_scenario(sc, include_greedy=not args.no_greedy,
                               reserve_margin_kw=args.reserve)
        except Exception as exc:
            print("[ERROR] 情景 {} 求解失败：{}".format(sc.name, exc), file=sys.stderr)
            print("        该情景的储能容量不足以在并网点限额内承接峰值负荷。"
                  "请增大 battery capacity_kwh / p_discharge_max_kw，"
                  "或降低 workload 峰值。", file=sys.stderr)
            continue
        results.append(res)
        _print_result(res)

    if not results:
        print("[ERROR] 没有任何情景成功求解。", file=sys.stderr)
        return 1

    paths = write_report(results, args.outdir, make_charts=not args.no_charts)
    print("")
    print("=" * 78)
    print("总耗时 {:.2f}s".format(time.time() - t0))
    print("报告: {}".format(paths["markdown"]))
    print("数据: {}".format(paths["csv"]))
    for name, files in paths["charts"].items():
        for f in files:
            print("图表: {}".format(f))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
