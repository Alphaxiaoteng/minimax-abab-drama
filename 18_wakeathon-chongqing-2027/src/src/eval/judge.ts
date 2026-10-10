/**
 * 评分引擎 —— 纯函数，输入 MetricReport，输出 0..100 的五维评分与封顶理由。
 *
 * 五维权重（合计 1.0）：
 *   视觉覆盖率 0.25 · 编排耦合 0.20 · 节奏曲线 0.20 · 确定性 0.15 · 鲁棒性 0.20
 *
 * 封顶规则（评委视角的「一票否决」）：
 *   1) 任一必需断言失败 → 该维度按失败数扣分，且总分封顶 79（不可进入优秀区）
 *   2) 出现 NaN / 引擎异常 → 总分封顶 59
 *   3) 覆盖率 < 0.5 → 总分封顶 69
 */
import type { EffectAssertion, MetricReport, SampleRow } from "./metrics";
import { ACTION_NAMES, meanOf, peakOf, seriesOf } from "./metrics";
import type { SceneRenderer } from "../core/contract";

export { ACTION_NAMES };

export interface DimensionScore {
  key: "coverage" | "coupling" | "rhythm" | "determinism" | "robustness";
  label: string;
  weight: number;
  raw: number;
  score: number;
}

export interface AssertionResult {
  note: string;
  action: string;
  pass: boolean;
  observed: number;
  required: number;
  kind: "peak" | "mean" | "absent";
}

export interface JudgeResult {
  total: number;
  grade: "S" | "A" | "B" | "C" | "D";
  dimensions: DimensionScore[];
  assertions: AssertionResult[];
  caps: string[];
  verdict: string;
}

export interface ScenarioLike {
  id: string;
  title: string;
  assertions: EffectAssertion[];
}

/** 断言求值：把「预期」翻译成客观读数判定 */
export function evaluateAssertions(
  rows: readonly SampleRow[],
  assertions: readonly EffectAssertion[],
): AssertionResult[] {
  return assertions.map((a) => {
    if (a.notAction) {
      const observed = peakOf(rows, a.notAction, a.window);
      const required = 0.05;
      return {
        note: a.note,
        action: a.notAction,
        pass: observed < required,
        observed,
        required,
        kind: "absent" as const,
      };
    }
    const action = a.action!;
    const wantMean = a.minMean !== undefined;
    const observed = wantMean ? meanOf(rows, action, a.window) : peakOf(rows, action, a.window);
    const required = (wantMean ? a.minMean : a.minPeak) ?? 0;
    return {
      note: a.note,
      action,
      pass: observed >= required - 1e-6,
      observed,
      required,
      kind: wantMean ? ("mean" as const) : ("peak" as const),
    };
  });
}

const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));

/**
 * 两个阵营各自持有的采样闭包：driver 在构造时注册，评测层只按 kind 取用。
 * 这样评测层不需要静态 import 任何具体阵营（浏览器 / Node 均可运行）。
 */
type Sampler = () => Record<string, number>;
const samplers: Partial<Record<SceneRenderer["kind"], Sampler>> = {};

export function registerSampler(kind: SceneRenderer["kind"], sampler: Sampler): void {
  samplers[kind] = sampler;
}

export function resetSampler(kind: SceneRenderer["kind"]): void {
  delete samplers[kind];
}

/** 节奏曲线分：峰值出现在后段 + 曲线有起伏（非平推） */
function rhythmScore(report: MetricReport): number {
  const rhythm = report.rhythm;
  if (rhythm.length < 3) return 0.5;
  const peaks = rhythm.map((r) => r.peak);
  const maxPeak = Math.max(...peaks, 1e-6);
  const maxIndex = peaks.indexOf(maxPeak);
  // 高潮位置：越靠后越好（留给后半程），但在倒数第二幕之前不苛求
  const position = maxIndex / (rhythm.length - 1);
  const lateBonus = clamp01(0.45 + position * 0.55);
  // 起伏度：峰值标准差 / 均值，过高过低都减分
  const mean = peaks.reduce((s, v) => s + v, 0) / peaks.length;
  const variance = peaks.reduce((s, v) => s + (v - mean) ** 2, 0) / peaks.length;
  const spread = Math.sqrt(variance) / (mean || 1);
  const dynamics = clamp01(1 - Math.abs(spread - 0.45) / 0.7);
  // 铺垫：首幕能量应低于峰值的一半
  const buildUp = clamp01(1 - peaks[0] / (maxPeak * 0.6));
  return clamp01(lateBonus * 0.45 + dynamics * 0.35 + buildUp * 0.2);
}

export function judge(report: MetricReport, scenario: ScenarioLike): JudgeResult {
  return judgeReport(report, scenario);
}

/** 正式入口：报告已含逐条断言与指标，直接加权 */
export function judgeReport(
  report: MetricReport,
  scenario: { id: string; title: string; assertions: readonly EffectAssertion[] },
): JudgeResult {
  const assertions = evaluateAssertions(rowsFromSeries(report), scenario.assertions);

  const failedRequired = assertions.filter((a) => !a.pass).length;
  const assertionRatio = assertions.length === 0 ? 1 : 1 - failedRequired / assertions.length;

  const coverage = clamp01(report.coverage * 0.65 + report.peakCoverage * 0.35);
  const coupling = clamp01(report.coupling);
  const rhythm = rhythmScore(report);
  const determinism = clamp01(report.determinism);
  const robustness = clamp01(report.robustness * 0.7 + assertionRatio * 0.3);

  const dimensions: DimensionScore[] = [
    { key: "coverage", label: "视觉覆盖率", weight: 0.25, raw: coverage, score: coverage * 100 },
    { key: "coupling", label: "编排耦合度", weight: 0.2, raw: coupling, score: coupling * 100 },
    { key: "rhythm", label: "节奏曲线", weight: 0.2, raw: rhythm, score: rhythm * 100 },
    { key: "determinism", label: "确定度", weight: 0.15, raw: determinism, score: determinism * 100 },
    { key: "robustness", label: "鲁棒性", weight: 0.2, raw: robustness, score: robustness * 100 },
  ];

  let total = dimensions.reduce((s, d) => s + d.score * d.weight, 0);
  const caps: string[] = [];

  if (!report.ok || report.error) {
    total = Math.min(total, 59);
    caps.push(`引擎异常：${report.error ?? "未知错误"} → 总分封顶 59`);
  }
  if (report.determinism < 0.999) {
    total = Math.min(total, 74);
    caps.push(`重放读数不一致（确定度 ${report.determinism.toFixed(3)}）→ 总分封顶 74`);
  }
  if (report.coverage < 0.5) {
    total = Math.min(total, 69);
    caps.push(`覆盖率 ${report.coverage.toFixed(2)} < 0.50 → 总分封顶 69`);
  }
  if (failedRequired > 0) {
    total = Math.min(total, 79);
    caps.push(`${failedRequired} 条断言未通过 → 总分封顶 79`);
  }

  const grade: JudgeResult["grade"] =
    total >= 90 ? "S" : total >= 82 ? "A" : total >= 72 ? "B" : total >= 60 ? "C" : "D";

  const weakest = [...dimensions].sort((a, b) => a.raw - b.raw)[0];
  const verdict =
    failedRequired === 0
      ? `${scenario.title}：满分项齐全，最弱维度为「${weakest.label}」（${(weakest.raw * 100).toFixed(1)}）`
      : `${scenario.title}：${failedRequired}/${assertions.length} 条断言未过，首要问题为「${assertions.find((a) => !a.pass)?.note}」`;

  return { total: Math.round(total * 10) / 10, grade, dimensions, assertions, caps, verdict };
}

/** 从报告的分段序列重建帧行（断言需要行式数据） */
export function rowsFromSeries(report: MetricReport): SampleRow[] {
  const rows: SampleRow[] = [];
  const template = report.series[ACTION_NAMES[0]];
  if (!template) return rows;
  for (let i = 0; i < template.length; i++) {
    const values: Record<string, number> = {};
    for (const action of ACTION_NAMES) values[action] = report.series[action]?.[i]?.[1] ?? 0;
    rows.push({ t: template[i][0], values });
  }
  return rows;
}

export { seriesOf };
