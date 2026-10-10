/**
 * rubric.ts 的确定性测试：权重、短板判定、各维度真实计算。
 */

import { describe, expect, it } from 'vitest';
import { EVAL_THRESHOLDS } from '../core/constants.js';
import { RUBRIC_SPEC, aggregate, scoreCase, scoreDimension } from './rubric.js';
import type { DimensionObservations, ScoredDimension, VoiceSample } from './rubric.js';

const findSpec = (id: string) => {
  const spec = RUBRIC_SPEC.find((s) => s.id === id);
  if (!spec) throw new Error(`缺少维度 ${id}`);
  return spec;
};

describe('RUBRIC_SPEC 结构', () => {
  it('维度至少 6 个，且六维 id 齐全', () => {
    expect(RUBRIC_SPEC.length).toBeGreaterThanOrEqual(6);
    for (const id of [
      'persona_fidelity',
      'emotion_accuracy',
      'voice_expressiveness',
      'fallback_robustness',
      'latency',
      'script_integrity',
    ]) {
      expect(RUBRIC_SPEC.some((s) => s.id === id)).toBe(true);
    }
  });

  it('权重之和必须为 1', () => {
    const sum = RUBRIC_SPEC.reduce((acc, s) => acc + s.weight, 0);
    expect(sum).toBeCloseTo(1, 10);
  });

  it('六个指定维度的权重取值与规格一致', () => {
    expect(findSpec('persona_fidelity').weight).toBe(0.22);
    expect(findSpec('emotion_accuracy').weight).toBe(0.2);
    expect(findSpec('voice_expressiveness').weight).toBe(0.18);
    expect(findSpec('fallback_robustness').weight).toBe(0.15);
    expect(findSpec('latency').weight).toBe(0.13);
    expect(findSpec('script_integrity').weight).toBe(0.12);
  });

  it('每个维度的 threshold 与 description 均为有效值', () => {
    for (const spec of RUBRIC_SPEC) {
      expect(spec.threshold).toBeGreaterThan(0);
      expect(spec.threshold).toBeLessThanOrEqual(1);
      expect(spec.description.length).toBeGreaterThan(0);
    }
  });
});

describe('各维度由观测真实计算（禁止常量）', () => {
  it('persona_fidelity：命中率随观测线性变化', () => {
    const spec = findSpec('persona_fidelity');
    expect(scoreDimension(spec, { personaHits: 8, personaTotal: 10 }).score).toBeCloseTo(0.8, 10);
    expect(scoreDimension(spec, { personaHits: 2, personaTotal: 10 }).score).toBeCloseTo(0.2, 10);
  });

  it('persona_fidelity：禁忌词违规施加惩罚（对半砍）', () => {
    const spec = findSpec('persona_fidelity');
    const clean = scoreDimension(spec, { personaHits: 10, personaTotal: 10 }).score;
    const dirty = scoreDimension(spec, { personaHits: 10, personaTotal: 10, tabooViolations: 1 }).score;
    expect(clean).toBe(1);
    expect(dirty).toBeCloseTo(0.5, 10);
  });

  it('emotion_accuracy：匹配率随逐位结果变化', () => {
    const spec = findSpec('emotion_accuracy');
    expect(scoreDimension(spec, { emotionExpected: 10, emotionCorrect: 7 }).score).toBeCloseTo(0.7, 10);
    expect(scoreDimension(spec, { emotionExpected: 10, emotionCorrect: 10 }).score).toBe(1);
  });

  it('voice_expressiveness：贴标签（参数全同）得 0，差异度越大得分越高', () => {
    const spec = findSpec('voice_expressiveness');
    const flat: VoiceSample[] = [
      { emotion: 'calm', speed: 1, vol: 1, pitch: 0 },
      { emotion: 'furious', speed: 1, vol: 1, pitch: 0 },
    ];
    const varied: VoiceSample[] = [
      { emotion: 'calm', speed: 0.9, vol: 1, pitch: -2 },
      { emotion: 'furious', speed: 1.4, vol: 6, pitch: 8 },
    ];
    expect(scoreDimension(spec, { voiceSamples: flat }).score).toBe(0);
    expect(scoreDimension(spec, { voiceSamples: varied }).score).toBeGreaterThan(0.2);
    // 样本不足两个无法体现差异，记 0
    expect(scoreDimension(spec, { voiceSamples: [varied[0]!] }).score).toBe(0);
  });

  it('fallback_robustness：无降级视为满分；有降级按成功率', () => {
    const spec = findSpec('fallback_robustness');
    expect(scoreDimension(spec, {}).score).toBe(1);
    expect(scoreDimension(spec, { fallbackAttempts: 5, fallbackSuccesses: 4 }).score).toBeCloseTo(0.8, 10);
  });

  it('latency：达标率按 latencyP95Ms 阈值统计', () => {
    const spec = findSpec('latency');
    const threshold = EVAL_THRESHOLDS.latencyP95Ms;
    const obs: DimensionObservations = {
      latencySamplesMs: [100, threshold, threshold + 1, 5000],
    };
    // 前两个 <= 阈值，后两个超 -> 2/4
    expect(scoreDimension(spec, obs).score).toBeCloseTo(0.5, 10);
  });

  it('script_integrity：抵达阶段 / 要求阶段', () => {
    const spec = findSpec('script_integrity');
    expect(scoreDimension(spec, { phasesVisited: 3, phasesRequired: 5 }).score).toBeCloseTo(0.6, 10);
    // 超额抵达也不越界
    expect(scoreDimension(spec, { phasesVisited: 9, phasesRequired: 5 }).score).toBe(1);
  });
});

describe('scoreCase', () => {
  it('达标观测产出 passed=true，未达标产出 passed=false', () => {
    const spec = findSpec('emotion_accuracy');
    const passCase = scoreCase(spec, { emotionExpected: 10, emotionCorrect: 10 });
    const failCase = scoreCase(spec, { emotionExpected: 10, emotionCorrect: 1 });
    expect(passCase.passed).toBe(true);
    expect(passCase.score).toBe(1);
    expect(failCase.passed).toBe(false);
    expect(passCase.expected).toContain(String(spec.threshold));
  });
});

describe('aggregate', () => {
  const full = (score: number, threshold: number, weight: number): ScoredDimension => ({
    id: 'x',
    name: 'x',
    weight,
    score,
    threshold,
    detail: '',
  });

  it('overall 为加权和', () => {
    const dims = RUBRIC_SPEC.map((s) => scoreDimension(s, {
      personaHits: 10,
      personaTotal: 10,
      emotionExpected: 10,
      emotionCorrect: 10,
      voiceSamples: [
        { emotion: 'calm', speed: 0.5, vol: 0.1, pitch: -12 },
        { emotion: 'furious', speed: 2, vol: 10, pitch: 12 },
      ],
      fallbackAttempts: 10,
      fallbackSuccesses: 10,
      latencySamplesMs: [100, 200],
      phasesVisited: 5,
      phasesRequired: 5,
    }));
    const expectedOverall = dims.reduce((acc, d) => acc + d.weight * d.score, 0);
    const result = aggregate(dims);
    expect(result.overall).toBeCloseTo(expectedOverall, 10);
    expect(result.passed).toBe(true);
  });

  it('单维度不达标即导致整体不通过（即使总分很高）', () => {
    const dims = [
      full(1, 0.5, 0.6),
      full(0.99, 0.95, 0.4), // score 0.99 >= 0.95 达标
    ];
    // 上面两维都达标 -> passed true，用于对比
    expect(aggregate(dims).passed).toBe(true);

    const broken = [
      full(1, 0.5, 0.85), // 高分大权重
      full(0.1, 0.9, 0.15), // 单点短板：0.1 < 0.9
    ];
    const res = aggregate(broken);
    expect(res.overall).toBeGreaterThanOrEqual(0.75); // 总分仍可能达标
    expect(res.passed).toBe(false); // 但短板维度否决整体
  });

  it('权重之和不为 1 的维度集合一律判不通过', () => {
    const res = aggregate([full(1, 0.5, 0.5), full(1, 0.5, 0.3)]);
    expect(res.passed).toBe(false);
  });
});