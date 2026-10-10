/**
 * consistency.ts 的确定性测试。
 */

import { describe, expect, it } from 'vitest';
import type { Emotion, Persona } from '../core/types.js';
import {
  measureEmotionAccuracy,
  measurePersonaConsistency,
  parseSentenceLengthRange,
  scriptedConversation,
} from './consistency.js';

const baseVoice = { base: { voiceId: 'v', speed: 1, vol: 1, pitch: 0, emotion: 'calm' as Emotion }, perEmotion: {} };

function fakePersona(overrides: Partial<Persona> = {}): Persona {
  return {
    id: 'p1',
    name: '测试',
    tagline: 't',
    biography: 'b',
    speechStyle: '句长 10 到 30 字',
    emotionalRange: ['calm'],
    catchphrases: ['有意思', '让我们'],
    taboos: ['脏话'],
    voice: baseVoice,
    openingLine: '开场',
    facts: {},
    ...overrides,
  };
}

describe('measurePersonaConsistency', () => {
  it('禁忌词命中直接 0 分并记 violation', () => {
    const persona = fakePersona();
    const result = measurePersonaConsistency(persona, ['有意思，让我们继续', '脏话']);
    expect(result.score).toBe(0);
    expect(result.violations).toContain('脏话');
  });

  it('口头禅命中增加 hits，且得分高于无命中', () => {
    const persona = fakePersona();
    const withCatchphrase = measurePersonaConsistency(persona, ['有意思，让我们慢慢梳理这段线索吧。']);
    const without = measurePersonaConsistency(persona, ['我不知道该说什么呢']);
    expect(withCatchphrase.hits).toBe(1);
    expect(without.hits).toBe(0);
    expect(withCatchphrase.score).toBeGreaterThan(without.score);
  });

  it('无回复时返回 0 分', () => {
    const result = measurePersonaConsistency(fakePersona(), []);
    expect(result.score).toBe(0);
    expect(result.detail).toContain('无有效回复');
  });

  it('得分范围始终在 0–1 之间', () => {
    const persona = fakePersona();
    for (const replies of [['有意思'], ['有意思，让我们走吧！', '有意思，让我们看看！'], []]) {
      const s = measurePersonaConsistency(persona, replies).score;
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(1);
    }
  });

  it('detail 包含中文可读统计', () => {
    const result = measurePersonaConsistency(fakePersona(), ['有意思，让我们继续吧。']);
    expect(result.detail).toContain('口头禅');
    expect(result.detail).toContain('句长合规率');
  });
});

describe('parseSentenceLengthRange', () => {
  it('从 speechStyle 抽取上下界', () => {
    expect(parseSentenceLengthRange('句长 10 到 30 字')).toEqual({ min: 10, max: 30 });
  });
  it('无数字时回落默认区间', () => {
    expect(parseSentenceLengthRange('简短')).toEqual({ min: 8, max: 40 });
  });
});

describe('measureEmotionAccuracy', () => {
  it('完全匹配得 1', () => {
    expect(measureEmotionAccuracy(['calm', 'joyful'], ['calm', 'joyful'])).toBe(1);
  });
  it('逐位比对，部分匹配按比例', () => {
    expect(measureEmotionAccuracy(['calm', 'joyful', 'tense'], ['calm', 'tense', 'tense'])).toBeCloseTo(2 / 3, 10);
  });
  it('长度不等按较短对齐，缺失位算错', () => {
    // expected 3, actual 1 -> 最多对 1 位，分母仍为 3
    expect(measureEmotionAccuracy(['calm', 'joyful', 'tense'], ['calm'])).toBeCloseTo(1 / 3, 10);
  });
  it('expected 为空视为满分', () => {
    expect(measureEmotionAccuracy([], ['calm'])).toBe(1);
  });
});

describe('scriptedConversation', () => {
  it('至少 12 轮', () => {
    expect(scriptedConversation().length).toBeGreaterThanOrEqual(12);
  });
  it('覆盖全部 8 种情绪', () => {
    const set = new Set(scriptedConversation().map((t) => t.expectEmotion));
    expect(set.size).toBe(8);
  });
  it('每轮 user 输入非空且为中文', () => {
    for (const turn of scriptedConversation()) {
      expect(turn.user.length).toBeGreaterThan(0);
      expect(/[一-鿿]/.test(turn.user)).toBe(true);
    }
  });
});