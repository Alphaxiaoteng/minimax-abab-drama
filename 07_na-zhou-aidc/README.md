# 钠电储能 × AIDC 算力中心削峰填谷智能调度

一句话定位：面向 AI 数据中心（AIDC）瞬态算力峰值场景，用线性规划（LP）调度电网侧钠离子储能做削峰填谷，量化电费节省、需量削减与 PUE 影响。

> 初焰·钠宙 线上黑客松 Season 01（赛事 ID `hackertrip-31ea58bc-a13b-4720-8cb6-b78701efd0ca`）研发工程。规则详见 [RULES.md](RULES.md)。

## 快速开始

```bash
# 1. 使用既有虚拟环境（勿新建 venv）
python3 -m venv .venv && source .venv/bin/activate   # 已有 .venv 可跳过
pip install -r requirements.txt

# 2. 运行全部情景的端到端仿真
python -m src.main --all

# 单情景 / 指定随机种子 / 指定输出目录
python -m src.main --scenario transient_spike --seed 7 --outdir reports
```

Docker 方式（LP 使用 PuLP 自带 CBC，slim 镜像无需额外求解器二进制）：

```bash
docker build -t na-aidc .
docker run --rm na-aidc              # 等价于 python -m src.main --all
```

## 目录结构

```
src/
  config.py       # 冻结接口：时间基准、Battery/DataCenter/Tariff 参数、Scenario、默认工厂
  types.py        # 结果容器：Schedule（调度轨迹）与 KPIs（指标汇总），含 as_dict()/rows()
  battery.py      # 钠电模型：SOC 动态、功率/效率/SOC 约束、循环老化成本；simulate_soc() 校验
  workload.py     # AIDC IT 负载：基线 + 泊松式瞬态训练尖峰，由 seed 确定性生成
  tariff.py       # 分时电价序列 + 最大需量电费计算
  optimizer.py    # PuLP 线性规划：build_model() 与 solve(scenario, it_power) -> Schedule
  pue.py          # PUE 分析：瞬时 PUE、有/无储能对比、PUE 分位数
  simulate.py     # 端到端：基线(无储能) / LP 最优 / 贪心策略对比，返回 Schedule+KPIs
  report.py       # 输出 Markdown 报告与 PNG 图表到 reports/
  main.py         # CLI 入口（argparse）：--scenario/--all/--seed/--outdir，打印汇总表并写报告
tests/            # pytest 单测，确定性、无网络
requirements.txt  # 依赖锁定（pulp 3.3.1 / numpy 2.0.2 / pandas 2.3.3 / matplotlib 3.9.4 / pytest 8.4.2）
Dockerfile        # python:3.11-slim 镜像
reports/          # 运行后生成的报告与图表（.gitignore 已忽略）
```

## 关键参数（取自 `src/config.py` 默认值，非结果数值）

| 对象 | 参数 | 默认值 |
|---|---|---|
| 时间 | N_STEPS / STEP_HOURS | 96 步 / 0.25 h（15 分钟，覆盖 24h） |
| 钠电 | capacity / p_charge_max / p_discharge_max | 2000 kWh / 500 kW / 500 kW |
| 钠电 | soc_min / soc_max / soc_init | 0.10 / 0.90 / 0.50 |
| 钠电 | eta_charge / eta_discharge | 0.95 / 0.95（往返 ≈ 0.9025） |
| 钠电 | cycle_life / capex_per_kwh / om_cost_per_kwh | 4000 次 / 900 元/kWh / 0.02 元/kWh |
| 数据中心 | it_base_kw / it_peak_kw | 3000 / 9000 |
| 数据中心 | transformer_limit_kw / grid_connection_kw | 8000 / 8000 |
| 数据中心 | cooling_ratio_base / pue_target / ups_loss_ratio | 0.32 / 1.25 / 0.03 |
| 数据中心 | demand_charge_per_kw | 42 元/kW/月 |
| 电价 | valley / flat / peak / sharp（元/kWh） | 0.30 / 0.62 / 0.98 / 1.28 |

分时时段见 `config.TOU_WINDOWS`（尖峰：10:00–11:00 与 19:00–21:00）。三个递进情景见 `default_scenarios()`：`baseline_day`、`transient_spike`、`extreme_peak`。

## 模型数学摘要（引自 `src/optimizer.py` docstring 与冻结契约）

逐步（t = 0..95）线性规划，决策变量为 `charge[t]`、`discharge[t]`、`grid_import[t]`，`soc[t]` 为端点 SOC：

- 功率平衡：`grid_import[t] + discharge[t] == it_power[t] + cooling[t] + charge[t] + ups_loss[t]`，其中 `ups_loss[t] = ups_loss_ratio · (it_power[t] + cooling[t])`。
- 并网点硬约束：`grid_import[t] <= grid_connection_kw`（储能须在变压器/并网容量内削峰）。
- SOC 递归：`soc[t] = soc[t-1] + (eta_charge·charge[t] − discharge[t]/eta_discharge) · STEP_HOURS / capacity_kwh`，`soc[-1]` 取 `soc_init`。
- SOC 与功率上下界：`soc_min ≤ soc[t] ≤ soc_max`，`0 ≤ charge[t] ≤ p_charge_max_kw`，`0 ≤ discharge[t] ≤ p_discharge_max_kw`。
- 老化成本（线性吞吐）：按放电侧等效全循环计量，单位吞吐老化成本 $c_{\mathrm{deg}} = \mathrm{capex\_per\_kwh} / \mathrm{cycle\_life}$（元/kWh 放电吞吐）；避免充电损耗重复计费，叠加运维成本得到总度电衰减成本。
- 目标（元，严格线性）：电度电费 + 最大需量电费（LP 内以标量上界变量线性化峰值 `grid_import`）+ 储能老化成本。

> 完整推导与实现以 `src/optimizer.py` 为准。

## 交付物清单

- [x] `src/` 可运行 Python LP 微网仿真（config/types/battery/workload/tariff/optimizer/pue/simulate/report/main）
- [x] `requirements.txt`（版本锁定）、`Dockerfile`、`.gitignore`
- [x] `tests/test_*.py` pytest 单测（确定性、无网络）
- [ ] 运行生成的 PUE/成本分析报告与图表：`reports/`

<!-- PLACEHOLDER: 运行 `python -m src.main --all` 后，报告与图表输出至 `reports/`；本文档不预填任何结果数值，所有指标均由运行时计算。 -->