/**
 * 评测指标层 —— 从「引擎状态读数」提取可判定的客观量。
 *
 * 设计原则：指标只依赖 `sample()` 读数与命令队列，不依赖任何渲染细节，
 * 因此 Three.js 阵营与 CSS 阵营可以用同一套指标比较。
 */
import type { ActionName, AgentTone } from "../core/contract";

export const ACTION_NAMES: readonly ActionName[] = [
  "fog",
  "skyline",
  "dawn",
  "fireworks",
  "laser",
  "drone",
  "mascot",
  "spotlight",
  "confetti",
  "glitch",
  "shatter",
];

export interface EffectAssertion {
  /** 断言该动作确实发生 */
  action?: ActionName;
  /** 断言该动作从未被触发 */
  notAction?: ActionName;
  /** 区间（相对大秀开始 ms） */
  window?: [number, number];
  /** 期望的采样区间 */
  range?: [number, number];
  /** [必需] 该区间内动作能量峰值下限 */
  minPeak?: number;
  /** [必需] 该区间内动作能量均值下限 */
  minMean?: number;
  /** 该断言在大秀第几幕采样（与 window 二选一，便于写用例） */
  plan?: number;
  /** 人类可读的失败原因 */
  note: string;
}

export interface Scenario {
  id: string;
  title: string;
  category: "show" | "intent" | "engine" | "robust";
  /** 送达意图文本（intent 类必填） */
  intents?: string[];
  /** 只放某一幕（0-based） */
  plan?: number;
  /** 缩放大秀倍速，默认 8（评测时加速重放） */
  speed?: number;
  /** 采样时长上限（ms） */
  durationMs?: number;
  assertions: EffectAssertion[];
  /** 是否需要引擎可用 */
  requireRenderer: boolean;
}

export interface SampleRow {
  t: number;
  values: Record<string, number>;
}

export interface MetricReport {
  id: string;
  title: string;
  category: Scenario["category"];
  /** 本次采样用了哪个阵营 */
  renderer: string;
  /** 动作名 → 分段线性函数 { t, v } 采样点，供断言与图表 */
  series: Record<string, Array<[number, number]>>;
  /** 覆盖率：用例里要求出现过的动作中，实际出现过的比例 0..1 */
  coverage: number;
  /** 峰值覆盖：所有 11 个动作中，至少出现一次峰值的比例 0..1 */
  peakCoverage: number;
  /** 峰值耦合度：预期动作同时活跃的重叠比 0..1 */
  coupling: number;
  /** 确定度：同 dt 序列重放两次，逐帧读数最大差值取反 0..1 */
  determinism: number;
  /** 鲁棒度：送达随机/异常意图后引擎未崩、未出现 NaN、读数仍有限 0..1 */
  robustness: number;
  /** 节奏谱：每个镜头（cue）的能量曲线特征 */
  rhythm: Array<{ cue: number; planIndex: number; peak: number; mean: number; holdMs: number }>;
  /** 采样点数 */
  frames: number;
  /** 未抛异常 */
  ok: boolean;
  error?: string;
  /** 事后核对：确实送达过的命令 */
  delivered: ActionName[];
  /** 逐动作峰值，供人工读表 */
  peaks: Record<string, number>;
}

const emptyValues = (): Record<string, number> =>
  Object.fromEntries(ACTION_NAMES.map((a) => [a, 0])) as Record<string, number>;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 逐帧记录 `sample()` 读数；渲染器必须实现 HarnessDriver 的 advance/sample */
export function recordFrames(
  advance: (dt: number) => void,
  sample: () => Record<string, number>,
  { durationMs, dt = 16.7, renderer }: { durationMs: number; dt?: number; renderer: string },
): { rows: SampleRow[]; nanHits: number; renderer: string } {
  const rows: SampleRow[] = [];
  let nanHits = 0;
  for (let t = 0; t < durationMs; t += dt) {
    advance(dt / 1000);
    const raw = sample();
    const values = emptyValues();
    for (const action of ACTION_NAMES) {
      const v = raw[action];
      if (v !== undefined && !finite(v)) nanHits += 1;
      values[action] = finite(v) ? Math.max(0, Math.min(1, v)) : 0;
    }
    rows.push({ t: Math.round(t), values });
  }
  return { rows, nanHits, renderer };
}

/* ── 指标计算 ── */

export function seriesOf(rows: readonly SampleRow[], action: ActionName): Array<[number, number]> {
  return rows.map((row) => [row.t, row.values[action]]);
}

export function peakOf(rows: readonly SampleRow[], action: ActionName, window?: [number, number]): number {
  const from = window?.[0] ?? 0;
  const to = window?.[1] ?? Infinity;
  let peak = 0;
  for (const row of rows) {
    if (row.t < from || row.t > to) continue;
    peak = Math.max(peak, row.values[action]);
  }
  return peak;
}

export function meanOf(rows: readonly SampleRow[], action: ActionName, window?: [number, number]): number {
  const from = window?.[0] ?? 0;
  const to = window?.[1] ?? Infinity;
  let sum = 0;
  let n = 0;
  for (const row of rows) {
    if (row.t < from || row.t > to) continue;
    sum += row.values[action];
    n += 1;
  }
  return n === 0 ? 0 : sum / n;
}

export function firstActiveAt(rows: readonly SampleRow[], action: ActionName, threshold = 0.05): number | null {
  for (const row of rows) if (row.values[action] >= threshold) return row.t;
  return null;
}

/** 覆盖率：预期集合中有多少比例真正亮过 */
export function coverageOf(rows: readonly SampleRow[], expected: readonly ActionName[]): number {
  if (expected.length === 0) return 1;
  const lit = expected.filter((a) => firstActiveAt(rows, a) !== null).length;
  return lit / expected.length;
}

/** 全场峰值覆盖：11 个动作里有多少至少亮到 0.35 */
export function peakCoverageOf(rows: readonly SampleRow[]): number {
  const lit = ACTION_NAMES.filter((a) => peakOf(rows, a) >= 0.35).length;
  return lit / ACTION_NAMES.length;
}

/**
 * 峰值耦合度：把「哪些动作在同一时刻活跃」的帧做共现统计，
 * 相邻两帧激活集合的 Jaccard 均值越高，说明多路效果越呈「编排」而非单点轮播。
 */
export function couplingOf(rows: readonly SampleRow[], threshold = 0.2): number {
  const active = rows.map((row) => ACTION_NAMES.filter((a) => row.values[a] >= threshold));
  let sum = 0;
  let n = 0;
  for (let i = 1; i < active.length; i++) {
    const a = new Set(active[i - 1]);
    const b = new Set(active[i]);
    const union = new Set([...a, ...b]);
    if (union.size === 0) continue;
    let inter = 0;
    for (const x of union) if (a.has(x) && b.has(x)) inter += 1;
    sum += inter / union.size;
    n += 1;
  }
  return n === 0 ? 0 : sum / n;
}

/** 情绪权重：用于评估播报语气与画面能量的匹配度（hype/warn 应配高能量帧） */
export const TONE_WEIGHT: Record<AgentTone, number> = { calm: 0.5, poetic: 0.6, hype: 0.85, warn: 0.7 };
