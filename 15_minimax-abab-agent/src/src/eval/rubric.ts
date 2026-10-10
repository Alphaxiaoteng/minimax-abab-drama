/**
 * 可配置评分器（SLICE D / eval）。
 *
 * 设计契约：
 * 1. RUBRIC_SPEC 六维权重之和必须为 1（由测试断言锁定）。
 * 2. 每个维度的得分都必须由真实观测输入计算得出，禁止返回常量。
 * 3. aggregate 的 passed 判定：总分达标 且 每一维自身达标——单点短板即整体失败。
 */

import type { EvalCaseResult, RubricDimension } from '../core/contracts.js';
import { EVAL_THRESHOLDS } from '../core/constants.js';

/** 单维度的评分规格（RubricDimension 的「静态定义」扩展，加入阈值与描述）。 */
export interface RubricSpec {
  readonly id: string;
  readonly name: string;
  /** 权重，六维之和必须为 1 */
  readonly weight: number;
  /** 维度自身的及格线（0–1） */
  readonly threshold: number;
  readonly description: string;
  /** 从观测输入计算 0–1 得分 */
  readonly compute: (observations: DimensionObservations) => number;
  /** 把观测输入翻译成中文可读说明 */
  readonly explain: (observations: DimensionObservations) => string;
}

/** 语音参数样本，用于「情绪参数差异度」维度。 */
export interface VoiceSample {
  readonly emotion: string;
  readonly speed: number;
  readonly vol: number;
  readonly pitch: number;
}

/** 评分观测输入。各维度只读取自己关心的字段，缺省视为「未观测」。 */
export interface DimensionObservations {
  /** persona_fidelity：命中口头禅的回复数 / 回复总数 / 禁忌词命中数 */
  readonly personaHits?: number;
  readonly personaTotal?: number;
  readonly tabooViolations?: number;
  /** emotion_accuracy：期望标签数 / 逐位匹配数 */
  readonly emotionExpected?: number;
  readonly emotionCorrect?: number;
  /** voice_expressiveness：各情绪的语音参数样本 */
  readonly voiceSamples?: readonly VoiceSample[];
  /** fallback_robustness：触发降级的调用数 / 降级后仍产出有效结果的调用数 */
  readonly fallbackAttempts?: number;
  readonly fallbackSuccesses?: number;
  /** latency：每轮延迟样本（毫秒） */
  readonly latencySamplesMs?: readonly number[];
  /** script_integrity：实际抵达的阶段数 / 剧本规定阶段数 */
  readonly phasesVisited?: number;
  readonly phasesRequired?: number;
}

/** 带阈值与得分的维度结果。 */
export interface ScoredDimension extends RubricDimension {
  readonly threshold: number;
}

const clamp01 = (v: number): number => Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0));

/** 口头禅命中率维度：禁忌词命中施加五折惩罚（置零逻辑在 consistency.ts 负责）。 */
function personaFidelityScore(o: DimensionObservations): number {
  const total = o.personaTotal ?? 0;
  if (total <= 0) return 0;
  const base = clamp01((o.personaHits ?? 0) / total);
  const violations = o.tabooViolations ?? 0;
  return clamp01(violations > 0 ? base * 0.5 : base);
}

/** 情绪逐位匹配率。 */
function emotionAccuracyScore(o: DimensionObservations): number {
  const expected = o.emotionExpected ?? 0;
  if (expected <= 0) return 0;
  return clamp01((o.emotionCorrect ?? 0) / expected);
}

/**
 * 情绪语音表现力：把 speed/vol/pitch 三个字段各自的极差除以协议合法量程，
 * 取平均作为差异度。所有样本参数一致（贴标签式实现）将得到 0。
 */
const VOICE_RANGES_RUBRIC = { speed: 1.5, vol: 9.9, pitch: 24 } as const; // 与 core VOICE_RANGES 对齐

function normalizedSpread(values: readonly number[], range: number): number {
  if (values.length < 2 || range <= 0) return 0;
  let min = values[0] as number;
  let max = min;
  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return clamp01((max - min) / range);
}

function voiceExpressivenessScore(o: DimensionObservations): number {
  const samples = o.voiceSamples ?? [];
  if (samples.length < 2) return 0;
  const spreads = [
    normalizedSpread(samples.map((s) => s.speed), VOICE_RANGES_RUBRIC.speed),
    normalizedSpread(samples.map((s) => s.vol), VOICE_RANGES_RUBRIC.vol),
    normalizedSpread(samples.map((s) => s.pitch), VOICE_RANGES_RUBRIC.pitch),
  ];
  return clamp01((spreads[0]! + spreads[1]! + spreads[2]!) / spreads.length);
}

/** 降级健壮性：降级发生时仍成功产出的比例；未触发降级视为满分。 */
function fallbackRobustnessScore(o: DimensionObservations): number {
  const attempts = o.fallbackAttempts ?? 0;
  if (attempts <= 0) return 1;
  return clamp01((o.fallbackSuccesses ?? 0) / attempts);
}

/** 延迟达标率：落在 P95 阈值以内的样本占比。 */
function latencyScore(o: DimensionObservations): number {
  const samples = o.latencySamplesMs ?? [];
  if (samples.length === 0) return 0;
  const ok = samples.filter((ms) => Number.isFinite(ms) && ms >= 0 && ms <= EVAL_THRESHOLDS.latencyP95Ms).length;
  return clamp01(ok / samples.length);
}

/** 剧本推进完整性：抵达阶段数 / 剧本阶段数。 */
function scriptIntegrityScore(o: DimensionObservations): number {
  const required = o.phasesRequired ?? 0;
  if (required <= 0) return 0;
  return clamp01(Math.min(o.phasesVisited ?? 0, required) / required);
}

export const RUBRIC_SPEC: readonly RubricSpec[] = [
  {
    id: 'persona_fidelity',
    name: '人格一致性',
    weight: 0.22,
    threshold: EVAL_THRESHOLDS.personaConsistency,
    description: '回复是否稳定命中口头禅、避开禁忌词',
    compute: personaFidelityScore,
    explain: (o) => `口头禅命中 ${o.personaHits ?? 0}/${o.personaTotal ?? 0} 条回复，禁忌词违规 ${o.tabooViolations ?? 0} 次`,
  },
  {
    id: 'emotion_accuracy',
    name: '情绪标注准确率',
    weight: 0.2,
    threshold: EVAL_THRESHOLDS.emotionAccuracy,
    description: '引擎输出的情绪标签与剧本期望逐位匹配的比例',
    compute: emotionAccuracyScore,
    explain: (o) => `情绪匹配 ${o.emotionCorrect ?? 0}/${o.emotionExpected ?? 0}`,
  },
  {
    id: 'voice_expressiveness',
    name: '语音表现力',
    weight: 0.18,
    threshold: 0.5,
    description: '不同情绪在 speed/vol/pitch 上产生可量化差异的比例（归一极差）',
    compute: voiceExpressivenessScore,
    explain: (o) => `参与统计的情绪语音样本 ${o.voiceSamples?.length ?? 0} 组`,
  },
  {
    id: 'fallback_robustness',
    name: '降级健壮性',
    weight: 0.15,
    threshold: 0.9,
    description: '传输层失败触发降级后仍产出有效结果的比例',
    compute: fallbackRobustnessScore,
    explain: (o) => `降级调用 ${o.fallbackAttempts ?? 0} 次，其中成功产出 ${(o.fallbackSuccesses ?? 0)} 次`,
  },
  {
    id: 'latency',
    name: '延迟达标率',
    weight: 0.13,
    threshold: 0.8,
    description: `单轮耗时不超过 ${EVAL_THRESHOLDS.latencyP95Ms}ms 的比例`,
    compute: latencyScore,
    explain: (o) => `延迟样本 ${o.latencySamplesMs?.length ?? 0} 个（阈值 ${EVAL_THRESHOLDS.latencyP95Ms}ms）`,
  },
  {
    id: 'script_integrity',
    name: '剧本推进完整性',
    weight: 0.12,
    threshold: 0.6,
    description: '会话阶段是否沿剧本方向推进到应有的深度',
    compute: scriptIntegrityScore,
    explain: (o) => `抵达阶段 ${o.phasesVisited ?? 0}/${o.phasesRequired ?? 0}`,
  },
];

/** 按规格观测一组数据，得到带阈值的维度结果。 */
export function scoreDimension(spec: RubricSpec, observations: DimensionObservations): ScoredDimension {
  return {
    id: spec.id,
    name: spec.name,
    weight: spec.weight,
    score: clamp01(spec.compute(observations)),
    threshold: spec.threshold,
    detail: spec.explain(observations),
  };
}

/** 把单个维度的一次观测封装成用例结果，用于报告的 cases 明细表。 */
export function scoreCase(spec: RubricSpec, observations: DimensionObservations): EvalCaseResult {
  const scored = scoreDimension(spec, observations);
  return {
    id: `${spec.id}_case`,
    passed: scored.score >= spec.threshold,
    score: scored.score,
    expected: `得分 >= ${spec.threshold}`,
    actual: scored.detail,
    note: `${spec.name}：${spec.description}`,
  };
}

/** 汇总：overall 为加权和；passed 要求总分与每一维同时达标。 */
export function aggregate(dimensions: readonly ScoredDimension[]): { overall: number; passed: boolean } {
  const overall = clamp01(dimensions.reduce((sum, d) => sum + d.weight * d.score, 0));
  const allWeightsAccounted = Math.abs(dimensions.reduce((sum, d) => sum + d.weight, 0) - 1) < 1e-9;
  const passed =
    allWeightsAccounted &&
    overall >= EVAL_THRESHOLDS.overallPass &&
    dimensions.every((d) => d.score >= d.threshold);
  return { overall, passed };
}
