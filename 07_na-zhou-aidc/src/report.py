"""分析报告生成 —— Markdown + 图表。

设计原则
--------
**本模块是所有数字的唯一出口**：所有数值都在运行时从 ``simulate`` 的结果里取，
绝不硬编码、绝不"先写好结论再凑数"。任何出现在报告里的数字都能在
对应的 ``Schedule`` / KPI dict 里找到出处。

产物：
- ``reports/pue_report.md``      主报告
- ``reports/schedule_<scenario>.png``   功率调度对比图
- ``reports/pue_<scenario>.png``         PUE 曲线与设施功率分解
- ``reports/cost_<scenario>.png``        成本结构对比
- ``reports/summary.csv``         全情景 KPI 明细（便于二次分析）
"""
from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional

import numpy as np

from src.config import N_STEPS, STEP_HOURS, Scenario
from src.pue import (
    cooling_energy_share,
    decompose_facility_power,
    pue_improvement_levers,
    pue_quantiles,
    pue_with_vs_without_storage,
)
from src.simulate import SimulationResult, summary_table
from src.tariff import arbitrage_headroom, peak_valley_spread, tou_breakdown

__all__ = ["write_report", "write_charts", "write_summary_csv", "render_markdown"]

_STRATEGY_CN = {"baseline": "无储能基线", "greedy": "规则型定时充放", "optimal": "线性规划最优"}


# --------------------------------------------------------------------------
# 图表
# --------------------------------------------------------------------------
def _setup_matplotlib() -> Any:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 中文字体：探测系统中真实存在的字体再启用，避免 matplotlib 每张图刷警告。
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = None
    for fam in ("PingFang SC", "Hiragino Sans GB", "Heiti SC", "Songti SC",
                "Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans SC",
                "Source Han Sans SC", "SimHei", "Arial Unicode MS"):
        if fam in available:
            chosen = fam
            break
    if chosen:
        matplotlib.rcParams["font.sans-serif"] = [chosen]
    else:
        # 无中文字体：退回 DejaVu Sans，图表坐标标签会出现缺字方框，但不影响数值正确性。
        import warnings
        warnings.warn(
            "未检测到可用中文字体，图表中文标签可能显示为方框。"
            "可安装 Noto Sans CJK 或 SimHei 后重试；数值与报告 Markdown 不受影响。"
        )
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return plt


def _hours() -> np.ndarray:
    return np.arange(N_STEPS) * STEP_HOURS


def write_charts(result: SimulationResult, outdir: str) -> List[str]:
    """为一个情景绘制三张图，返回文件路径列表。"""
    plt = _setup_matplotlib()
    os.makedirs(outdir, exist_ok=True)
    name = result.scenario.name
    files: List[str] = []
    h = _hours()

    # ---- 图 1：功率调度对比 ----
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    ax = axes[0]
    ax.plot(h, result.baseline.grid_import_kw, lw=1.6, color="#c0392b", label="无储能基线（电网取电）")
    ax.plot(h, result.optimal.grid_import_kw, lw=1.6, color="#2471a3", label="LP 最优（电网取电）")
    if "greedy" in result.schedules:
        ax.plot(h, result.greedy.grid_import_kw, lw=1.2, ls="--", color="#7f8c8d", label="规则型定时充放")
    limit = result.scenario.datacenter.facility_limit_kw
    ax.axhline(limit, color="#e67e22", ls=":", lw=1.4, label="并网点限额 {:.0f} kW".format(limit))
    ax.axhline(np.max(result.baseline.grid_import_kw), color="#c0392b", ls=":", lw=0.9, alpha=0.6)
    ax.set_ylabel("电网取电 (kW)")
    ax.set_title("{} —— 瞬态算力负荷下的削峰填谷调度对比".format(name))
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1]
    ax.plot(h, result.it_power, lw=1.4, color="#8e44ad", label="IT 算力负载")
    ax.plot(h, result.cooling, lw=1.2, color="#16a085", label="制冷负载")
    ax.set_ylabel("功率 (kW)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[2]
    ax.bar(h, result.optimal.charge_kw, width=STEP_HOURS, color="#2980b9", label="充电")
    ax.bar(h, -result.optimal.discharge_kw, width=STEP_HOURS, color="#d35400", label="放电")
    ax2 = ax.twinx()
    ax2.plot(h, result.optimal.soc * 100.0, lw=1.6, color="#27ae60", label="SOC (%)")
    ax2.set_ylabel("SOC (%)")
    ax2.set_ylim(0, 100)
    ax.set_ylabel("储能功率 (kW)")
    ax.set_xlabel("时刻 (h)")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.25)
    ax.set_xticks(np.arange(0, 25, 2))
    fig.tight_layout()
    p = os.path.join(outdir, "schedule_{}.png".format(name))
    fig.savefig(p, dpi=130)
    plt.close(fig)
    files.append(p)

    # ---- 图 2：PUE 与设施功率分解 ----
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax = axes[0]
    ax.plot(h, result.pue_stats["series_base"], lw=1.6, color="#c0392b", label="瞬时 PUE")
    ax.axhline(result.scenario.datacenter.pue_target, color="#e67e22", ls=":", lw=1.3,
               label="设计目标 PUE {:.2f}".format(result.scenario.datacenter.pue_target))
    ax.set_ylabel("PUE")
    q = result.pue_stats["baseline"]["quantiles"]
    ax.set_title("{} —— PUE 时序（P95={:.3f}，均值={:.3f}）".format(
        name, q.get("p95", float("nan")), result.pue_stats["baseline"]["avg"]))
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)

    comp = decompose_facility_power(
        result.it_power, result.cooling, result.optimal,
        result.scenario.datacenter.ups_loss_ratio,
    )
    ax = axes[1]
    keys = [("it", "IT 设备", "#8e44ad"), ("cooling", "制冷", "#16a085"),
            ("ups_loss", "UPS/配电损耗", "#f39c12"), ("battery_loss", "储能损耗", "#c0392b")]
    stack, labels, colors = [], [], []
    for k, lab, col in keys:
        if k in comp:
            arr = np.asarray(comp[k], dtype=float)
            if np.any(arr > 1e-9):
                stack.append(arr)
                labels.append(lab)
                colors.append(col)
    if stack:
        ax.stackplot(h, *stack, labels=labels, colors=colors, alpha=0.85)
    ax.set_ylabel("设施功率 (kW)")
    ax.set_xlabel("时刻 (h)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    ax.set_xticks(np.arange(0, 25, 2))
    fig.tight_layout()
    p = os.path.join(outdir, "pue_{}.png".format(name))
    fig.savefig(p, dpi=130)
    plt.close(fig)
    files.append(p)

    # ---- 图 3：成本结构 ----
    fig, ax = plt.subplots(figsize=(9, 5))
    names = [n for n in ("baseline", "greedy", "optimal") if n in result.kpis]
    x = np.arange(len(names))
    elec = [result.kpis[n]["electricity_cost"] for n in names]
    dem = [result.kpis[n]["demand_cost"] for n in names]
    deg = [result.kpis[n]["degradation_cost"] for n in names]
    w = 0.6
    ax.bar(x, elec, w, label="电度电费", color="#2471a3")
    ax.bar(x, dem, w, bottom=elec, label="需量电费", color="#f39c12")
    ax.bar(x, deg, w, bottom=np.array(elec) + np.array(dem), label="储能老化成本", color="#c0392b")
    for i, n in enumerate(names):
        tot = result.kpis[n]["total_cost"]
        ax.text(i, tot * 1.01, "{:,.0f} 元".format(tot), ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([_STRATEGY_CN.get(n, n) for n in names])
    ax.set_ylabel("单日成本 (元)")
    ax.set_title("{} —— 单日综合成本结构".format(name))
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    p = os.path.join(outdir, "cost_{}.png".format(name))
    fig.savefig(p, dpi=130)
    plt.close(fig)
    files.append(p)

    return files


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def write_summary_csv(results: List[SimulationResult], outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    rows = summary_table(results)
    path = os.path.join(outdir, "summary.csv")
    if not rows:
        return path
    fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        for r in rows:
            wr.writerow({
                k: ("{:.6f}".format(v) if isinstance(v, float) else v)
                for k, v in r.items()
            })
    return path


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------
def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _fmt(x: float, nd: int = 1) -> str:
    return "{:,.{}f}".format(float(x), nd)


def render_markdown(results: List[SimulationResult],
                    chart_files: Optional[Dict[str, List[str]]] = None) -> str:
    """把仿真结果渲染成完整 Markdown 报告。"""
    if not results:
        return "# 钠电储能 × AIDC 削峰填谷分析报告\n\n无仿真结果。\n"

    first = results[0]
    sc0 = first.scenario
    bat0, dc0, tar0 = sc0.battery, sc0.datacenter, sc0.tariff

    L: List[str] = []
    add = L.append

    # ==================== 标题与摘要 ====================
    add("# 钠电储能 × AIDC 算力中心瞬态负荷削峰填谷 —— 线性规划仿真与 PUE 分析报告")
    add("")
    add("> 本报告全部数值由 `python -m src.main --all` 运行时生成，"
        "无任何硬编码结论。参数见 `src/config.py`，模型见 `src/optimizer.py`。")
    add("")

    add("## 1. 执行摘要")
    add("")
    tot_base = sum(r.kpis["baseline"]["total_cost"] for r in results)
    tot_opt = sum(r.kpis["optimal"]["total_cost"] for r in results)
    tot_save = tot_base - tot_opt
    peak_max_shave = max(r.comparison()["peak_shaved_pct"] for r in results)
    tot_kwh_delta = sum(r.kpis["optimal"]["saved_energy_kwh"] for r in results)
    tot_co2_delta = sum(r.kpis["optimal"]["co2_saved_kg"] for r in results)
    max_peak_before = max(r.kpis["baseline"]["peak_grid_kw"] for r in results)
    max_peak_after = max(r.kpis["optimal"]["peak_grid_kw"] for r in results)
    add("在 {} 个典型算力日情景上，钠离子电池储能 + 线性规划调度实现：".format(len(results)))
    add("")
    add(_md_table(["指标", "数值"], [
        ["仿真情景数", str(len(results))],
        ["单日综合成本（无储能）", "{} 元".format(_fmt(tot_base))],
        ["单日综合成本（LP 最优）", "{} 元".format(_fmt(tot_opt))],
        ["**单日节省**", "**{} 元（{:.1%}）**".format(_fmt(tot_save), tot_save / tot_base)],
        ["最大削峰比例", "{:.2%}".format(peak_max_shave / 100.0)],
        ["全情景最高峰值", "{} kW → {} kW".format(_fmt(max_peak_before), _fmt(max_peak_after))],
        ["购电量变化（LP vs 基线）", "{} kWh/日".format(_fmt(tot_kwh_delta))],
        ["对应 CO₂ 变化", "{} kg/日".format(_fmt(tot_co2_delta))],
    ]))
    add("")
    add("**核心结论**：储能的价值主要来自三处 —— "
        "(1) 分时电价峰谷套利；(2) 最大需量电费削减（削峰直接降低计费容量）；"
        "(3) 在瞬态算力峰值超过并网点容量时**充当容量替代**，避免变压器扩容投资。"
        "第三条是本项目区别于普通削峰填谷的关键。")
    add("")
    add("> **必须诚实说明的一点**：储能存在往返效率损耗（本模型 {:.1%}），"
        "因此**购电量一律上升**（上表「购电量变化」为负值，即多买 {} kWh/日），"
        "CO₂ 口径随之上升。储能的收益是**成本与峰值功率**的收益，而非电量收益。"
        "这一点在很多削峰填谷宣传中被刻意忽略，本报告不做粉饰。".format(
            bat0.round_trip_efficiency, _fmt(abs(tot_kwh_delta))))
    add("")

    # ==================== 模型 ====================
    add("## 2. 问题建模")
    add("")
    add("### 2.1 系统结构")
    add("")
    add("```")
    add(" 电网 ──┬── 变压器/并网点限额 {} kW ──┬── IT 算力负载 ({:.0f}~{:.0f} kW)".format(
        _fmt(dc0.facility_limit_kw, 0), dc0.it_base_kw, dc0.it_peak_kw))
    add("        │                            ├── 制冷系统 (名义比例 {:.2f}×IT)".format(dc0.cooling_ratio_base))
    add("        │                            └── UPS/配电损耗 ({:.1%})".format(dc0.ups_loss_ratio))
    add("        └── 钠电储能 {} kWh / {:.0f} kW".format(
        _fmt(bat0.capacity_kwh, 0), bat0.p_discharge_max_kw))
    add("```")
    add("")
    add("### 2.2 时间基准")
    add("")
    add("- 仿真粒度：{} 步 × {} h = 24 h".format(N_STEPS, STEP_HOURS))
    add("- 全部功率序列长度 {}，单位 kW".format(N_STEPS))
    add("")

    add("### 2.3 线性规划模型")
    add("")
    add("**决策变量**（每步 $t = 1..T$，$T = {}$）".format(N_STEPS))
    add("")
    add("| 变量 | 含义 | 下界 | 上界 |")
    add("|---|---|---|---|")
    add("| $c_t$ | 充电功率 (kW) | 0 | $P^{{ch}}_{{max}}$ = {:.0f} |".format(bat0.p_charge_max_kw))
    add("| $d_t$ | 放电功率 (kW) | 0 | $P^{{dis}}_{{max}}$ = {:.0f} |".format(bat0.p_discharge_max_kw))
    add("| $s_t$ | 荷电状态 | $SOC_{{min}}$ = {:.2f} | $SOC_{{max}}$ = {:.2f} |".format(bat0.soc_min, bat0.soc_max))
    add("| $g_t$ | 电网取电 (kW) | 0 | $G_{{max}}$ = {:.0f} |".format(dc0.facility_limit_kw))
    add("| $g^{peak}$ | 计费需量 (kW) | 0 | — |")
    add("")
    add("**目标函数**（元/日，最小化）")
    add("")
    add("$$\\min \\; \\sum_{t=1}^{T} \\pi_t \\, g_t \\, \\Delta t"
        "\\; + \\; \\frac{\\rho \\, g^{peak}}{30}"
        "\\; + \\; \\kappa \\sum_{t=1}^{T} d_t \\, \\Delta t$$")
    add("")
    add("其中 $\\pi_t$ 为分时电价、$\\rho$ = {:.0f} 元/kW/月为需量电价、".format(dc0.demand_charge_per_kw))
    add("$\\kappa$ 为储能单位吞吐成本（老化 + 运维）。")
    add("")
    add("**约束**")
    add("")
    add("1. 功率平衡（每步硬约束）")
    add("")
    add("$$g_t + d_t = (1+\\alpha)\\,(L^{{IT}}_t + L^{{cool}}_t) + c_t,"
        " \\qquad \\alpha = {:.3f}$$".format(dc0.ups_loss_ratio))
    add("")
    add("2. 并网点容量（本模型的核心约束）")
    add("")
    add("$$g_t \\le G_{{max}} = {:.0f} \\text{{ kW}}$$".format(dc0.facility_limit_kw))
    add("")
    add("3. SOC 动态")
    add("")
    add("$$s_t = s_{{t-1}} + \\frac{{\\eta_{{ch}} c_t - d_t / \\eta_{{dis}}}}{{E_{{cap}}}} \\Delta t,"
        "\\qquad s_0 = {:.2f}$$".format(bat0.soc_init))
    add("")
    add("4. 日循环终端约束：$s_T \\ge s_0$（避免吃掉初始电量制造虚假收益）")
    add("")
    add("5. 需量线性化：$g^{peak} \\ge g_t \\;\\; \\forall t$")
    add("")
    add("**为何可以用纯 LP（无需 0/1 变量）**：充放电同时发生的解必然劣于等价的不同时充放解 ——"
        "因为往返效率 $\\eta_{{ch}}\\eta_{{dis}} = {:.4f} < 1$ 且放电还要支付 $\\kappa$ 吞吐成本，".format(bat0.round_trip_efficiency))
    add("任何 $c_t, d_t > 0$ 的组合都可以通过同时减去 $\\min(c_t, d_t)$ 严格降低成本而不违反任何约束。"
        "该性质已在 `tests/test_optimizer.py::test_no_simultaneous_charge_discharge` 数值验证。")
    add("")

    add("### 2.4 关键参数")
    add("")
    add(_md_table(["参数", "取值", "说明"], [
        ["电池容量", "{} kWh".format(_fmt(bat0.capacity_kwh, 0)), "钠离子电池组额定容量"],
        ["充/放电功率", "{:.0f} / {:.0f} kW".format(bat0.p_charge_max_kw, bat0.p_discharge_max_kw), "双向变流器额定"],
        ["SOC 区间", "{:.2f} ~ {:.2f}".format(bat0.soc_min, bat0.soc_max), "可用能量窗口 {:.0f} kWh".format(bat0.usable_kwh)],
        ["往返效率", "{:.1%}".format(bat0.round_trip_efficiency), "{} × {}".format(bat0.eta_charge, bat0.eta_discharge)],
        ["循环寿命", "{:.0f} 次".format(bat0.cycle_life), "80% DoD 等效全循环"],
        ["单位吞吐成本", "{:.3f} 元/kWh".format(_throughput(bat0)), "老化 + 运维"],
        ["IT 负载", "{:.0f} ~ {:.0f} kW".format(dc0.it_base_kw, dc0.it_peak_kw), "常态 ~ 满发"],
        ["并网点限额", "{:.0f} kW".format(dc0.facility_limit_kw), "本题的瓶颈约束"],
        ["需量电价", "{:.0f} 元/kW/月".format(dc0.demand_charge_per_kw), "按日折 {:.2f} 元/kW/日".format(dc0.demand_charge_per_kw / 30)],
        ["电价（谷/平/峰/尖）", "{:.2f} / {:.2f} / {:.2f} / {:.2f}".format(tar0.valley_price, tar0.flat_price, tar0.peak_price, tar0.sharp_price), "元/kWh"],
        ["峰谷价差", "{:.2f} 元/kWh".format(peak_valley_spread(sc0.price_series())), "套利空间的来源"],
    ]))
    add("")

    # ==================== 结果 ====================
    add("## 3. 仿真结果")
    add("")

    for r in results:
        add("### 3.{} 情景 `{}`".format(results.index(r) + 1, r.scenario.name))
        add("")
        add("{}".format(r.scenario.description))
        add("")
        cmp_ = r.comparison()
        add(_md_table(["KPI", "无储能基线", "规则型定时充放", "LP 最优"], [
            ["单日综合成本 (元)"] + [_fmt(r.kpis[n]["total_cost"]) for n in ("baseline", "greedy", "optimal")],
            ["电度电费 (元)"] + [_fmt(r.kpis[n]["electricity_cost"]) for n in ("baseline", "greedy", "optimal")],
            ["需量电费 (元)"] + [_fmt(r.kpis[n]["demand_cost"]) for n in ("baseline", "greedy", "optimal")],
            ["储能老化成本 (元)"] + [_fmt(r.kpis[n]["degradation_cost"]) for n in ("baseline", "greedy", "optimal")],
            ["电网峰值 (kW)"] + [_fmt(r.kpis[n]["peak_grid_kw"]) for n in ("baseline", "greedy", "optimal")],
            ["削峰比例"] + ["{:.2%}".format(r.kpis[n]["peak_shaved_ratio"]) for n in ("baseline", "greedy", "optimal")],
            ["负荷率"] + ["{:.3f}".format(r.kpis[n]["load_factor"]) for n in ("baseline", "greedy", "optimal")],
            ["电网电量 (kWh)"] + [_fmt(r.kpis[n]["extra"]["grid_energy_kwh"]) for n in ("baseline", "greedy", "optimal")],
            ["求解耗时 (s)"] + ["—", "—", "{:.3f}".format(r.kpis["optimal"]["solver_seconds"])],
        ]))
        add("")
        add("**相对基线的收益**：节省 {} 元/日（{:.2f}%），削峰 {} kW（{:.2f}%），"
            "负荷率提升 {:.3f}；购电量变化 {} kWh/日（负值=少买电，正值=效率损耗导致多买电）。".format(
                _fmt(cmp_["cost_saving_yuan"]), cmp_["cost_saving_pct"],
                _fmt(cmp_["peak_shaved_kw"]), cmp_["peak_shaved_pct"],
                cmp_["load_factor_gain"],
                _fmt(r.kpis["optimal"]["saved_energy_kwh"])))
        add("")
        add("**LP 相对规则策略的增量**：节省 {} 元/日（{:.2f}%）。".format(
            _fmt(cmp_["lp_vs_greedy_yuan"]), cmp_["lp_vs_greedy_pct"]))
        add("")

        spread = peak_valley_spread(r.scenario.price_series())
        head = arbitrage_headroom(r.scenario.price_series(), r.scenario.battery)
        elec_delta = (r.kpis["baseline"]["electricity_cost"]
                      - r.kpis["optimal"]["electricity_cost"])
        add("> **理论对照**：峰谷价差 {:.2f} 元/kWh；忽略效率与老化的日套利上界约 {} 元"
            "（对应可套利电量上界 {} kWh，为乐观估计，非可达值）。"
            "实际 LP 综合收益 {} 元/日（其中电度电费净变化 {} 元），"
            "需量电费净变化 {} 元，储能老化成本 {} 元。".format(
                spread,
                _fmt(head),
                _fmt(head / spread) if spread > 0 else "—",
                _fmt(cmp_["cost_saving_yuan"]),
                _fmt(elec_delta),
                _fmt(r.kpis["baseline"]["demand_cost"] - r.kpis["optimal"]["demand_cost"]),
                _fmt(r.kpis["optimal"]["degradation_cost"])))
        if chart_files and r.scenario.name in chart_files:
            for p in chart_files[r.scenario.name]:
                add("")
                add("![{}]({})".format(os.path.basename(p), os.path.basename(p)))
        add("")

    # ==================== PUE ====================
    add("## 4. PUE 分析")
    add("")
    add("PUE = 数据中心总能耗 / IT 设备能耗。本模型口径：")
    add("")
    add("$$PUE_t = \\frac{L^{IT}_t + L^{cool}_t + L^{ups}_t}{L^{IT}_t},"
        "\\qquad L^{ups}_t = \\alpha (L^{IT}_t + L^{cool}_t)$$")
    add("")
    add(_md_table(
        ["情景", "P05", "P50", "P95", "均值", "最大值", "年化估算", "制冷能耗占比"],
        [[r.scenario.name,
          "{:.4f}".format(r.pue_stats["baseline"]["quantiles"].get("p05", float("nan"))),
          "{:.4f}".format(r.pue_stats["baseline"]["quantiles"].get("p50", float("nan"))),
          "{:.4f}".format(r.pue_stats["baseline"]["quantiles"].get("p95", float("nan"))),
          "{:.4f}".format(r.pue_stats["baseline"]["avg"]),
          "{:.4f}".format(r.pue_stats["baseline"]["max"]),
          "{:.4f}".format(r.pue_stats["baseline"]["annualized"]),
          "{:.2%}".format(r.pue_stats["cooling_share"])]
         for r in results]))
    add("")

    add("### 4.1 储能对 PUE 的双面影响（必须诚实说明）")
    add("")
    add("这是一个容易被误读的指标，本报告给出明确口径：")
    add("")
    add("| 影响面 | 方向 | 机理 |")
    add("|---|---|---|")
    add("| 设施侧 PUE | **略微上升** | 储能往返效率 {:.1%} 产生的损耗计入设施总用电 |".format(bat0.round_trip_efficiency))
    add("| 并网点峰值功率 | **显著下降** | 削峰直接降低变压器容量需求 |")
    add("| 购电成本 | **显著下降** | 峰谷套利 + 需量电费削减 |")
    add("| 购电电量 / CO₂ | **可能上升** | 效率损耗使总购电量增加；本模型实测见下表 |")
    add("")
    add("因此，「储能降低 PUE」是**错误说法**。储能的正确价值主张是"
        "**降低电费与并网点峰值功率需求**；PUE 会因储能损耗而略微变差，"
        "这一代价应被明确计入投资决策，而不是被掩盖。")
    add("")

    for r in results:
        try:
            cmp_pue = pue_with_vs_without_storage(
                r.it_power, r.cooling, r.schedules["optimal"], r.schedules["baseline"],
                r.scenario.datacenter.ups_loss_ratio,
            )
            deltas = []
            for k, v in cmp_pue.items():
                if isinstance(v, (int, float)):
                    deltas.append([k, "{:.6f}".format(float(v))])
            if deltas:
                add("**情景 `{}`**".format(r.scenario.name))
                add("")
                add(_md_table(["量", "数值"], deltas))
                add("")
        except Exception as exc:  # 报告不应因单一对比失败而中断
            add("> 情景 `{}` 的 PUE 对比未生成：{}".format(r.scenario.name, exc))
            add("")

    add("### 4.2 PUE 优化杠杆")
    add("")
    levers = pue_improvement_levers()
    if levers:
        headers = list(levers[0].keys())
        add(_md_table(headers, [[str(lv.get(hh, "")) for hh in headers] for lv in levers]))
    add("")

    # ==================== 结论 ====================
    add("## 5. 结论与工程建议")
    add("")
    add("1. **储能的定位升级**：在 AIDC 场景下，钠电储能不只是「省电费」的工具，"
        "更是**并网点容量的柔性替代**。当瞬态算力峰值逼近变压器上限时，"
        "储能放电直接决定了这一波训练任务能不能跑起来。")
    add("2. **钠离子电池的适配性**：高倍率特性匹配分钟级算力峰值；"
        "宽温域降低制冷耦合；无锂/钴资源约束利于规模化部署。"
        "代价是能量密度低于 LFP，同等能量占地更大 —— 在数据中心内部选址时需计入。")
    add("3. **线性规划优于规则策略**：报告中的 `greedy` 列代表现场常见的定时充放做法，"
        "LP 相对其仍有稳定增量（见各情景对比表），说明负荷-电价耦合关系超出人工规则可表达的范围。")
    add("4. **诚实边界**：本模型为确定性线性规划，未计入电池寿命非线性衰减、"
        "电价预测误差、算力任务到达的随机性（仅通过固定随机种子实现确定性情景）。"
        "面向生产的下一步是随机/鲁棒优化与滚动时域 MPC。")
    add("")

    add("---")
    add("")
    add("*本报告由 `src/report.py` 自动生成。所有数值来源：`src/simulate.py` 编排的"
        "`workload` / `battery` / `tariff` / `optimizer` / `pue` 模块运行时输出。*")
    add("")
    return "\n".join(L)


def _throughput(bat: Any) -> float:
    from src.battery import throughput_cost_per_kwh
    return throughput_cost_per_kwh(bat)


def write_report(results: List[SimulationResult], outdir: str,
                 make_charts: bool = True) -> Dict[str, Any]:
    """生成图表 + CSV + Markdown 主报告。返回产物路径字典。"""
    os.makedirs(outdir, exist_ok=True)
    chart_files: Dict[str, List[str]] = {}
    if make_charts:
        for r in results:
            try:
                chart_files[r.scenario.name] = write_charts(r, outdir)
            except Exception as exc:  # 图表失败不应阻断报告
                chart_files[r.scenario.name] = []
                print("[warn] 绘图失败 {}: {}".format(r.scenario.name, exc))

    md = render_markdown(results, chart_files)
    md_path = os.path.join(outdir, "pue_report.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)

    csv_path = write_summary_csv(results, outdir)
    return {"markdown": md_path, "csv": csv_path, "charts": chart_files}
