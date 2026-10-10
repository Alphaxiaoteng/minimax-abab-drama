/**
 * 人格一致性量化（SLICE D / eval）。
 *
 * 契约：
 * 1. 纯确定性：不读取 Date/Math.random，只依据入参与固定语言规则计算。
 * 2. 禁忌词命中一票否决——直接 0 分并记 violation。
 * 3. 语言指纹（句长/第一人称/强弱标点）以归一化子分参与加权，保证可复算。
 */

import { EMOTIONS } from '../core/types.js';
import type { Emotion, Persona } from '../core/types.js';

/** 人格一致性度量结果。 */
export interface PersonaConsistencyResult {
  readonly score: number; // 0–1
  readonly hits: number; // 命中口头禅的回复数
  readonly violations: string[]; // 命中的禁忌词列表
  readonly detail: string; // 中文可读说明
}

/** 剧本回归对话的一轮：用户输入 + 期望引擎产出的情绪。 */
export interface ScriptedTurn {
  readonly user: string;
  readonly expectEmotion: Emotion;
}

const clamp01 = (v: number): number => Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0));

/** 按 Unicode 码点计数，绝不把半个汉字算进去。 */
function codepointLength(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** 从 speechStyle 文本里抽取「期望句长区间」，找不到则回落默认 [8,40]。 */
export function parseSentenceLengthRange(speechStyle: string): { min: number; max: number } {
  const nums = (speechStyle.match(/\d+/g) ?? []).map(Number).filter((n) => Number.isFinite(n) && n > 0 && n < 500);
  if (nums.length >= 2) {
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    if (min < max) return { min, max };
  }
  if (nums.length === 1) {
    const around = nums[0]!;
    return { min: Math.max(2, Math.floor(around * 0.6)), max: Math.ceil(around * 1.6) };
  }
  return { min: 8, max: 40 };
}

/** 把一个回复切成句子（中文标点为主）。 */
function splitSentences(reply: string): string[] {
  return reply
    .split(/[。！？!?；;\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * 计算人格一致性得分。
 * 组成：口头禅覆盖 50% + 语言指纹 50%（句长合规 0.5 / 第一人称 0.25 / 强弱标点 0.25）。
 */
export function measurePersonaConsistency(
  persona: Persona,
  replies: readonly string[],
): PersonaConsistencyResult {
  const nonEmpty = replies.filter((r) => r.trim().length > 0);

  // 禁忌词一票否决
  const violations: string[] = [];
  for (const taboo of persona.taboos) {
    if (taboo.length > 0 && nonEmpty.some((reply) => reply.includes(taboo))) {
      violations.push(taboo);
    }
  }
  if (violations.length > 0) {
    return {
      score: 0,
      hits: 0,
      violations,
      detail: `命中禁忌词「${violations.join('、')}」，人格一致性直接判 0 分`,
    };
  }

  if (nonEmpty.length === 0) {
    return { score: 0, hits: 0, violations: [], detail: '无有效回复可供评测' };
  }

  // 口头禅覆盖率
  let hits = 0;
  for (const reply of nonEmpty) {
    if (persona.catchphrases.some((cp) => cp.length > 0 && reply.includes(cp))) hits += 1;
  }
  const catchphraseCoverage = persona.catchphrases.length > 0 ? hits / nonEmpty.length : 1;

  // 语言指纹
  const { min, max } = parseSentenceLengthRange(persona.speechStyle);
  const sentences = nonEmpty.flatMap(splitSentences);
  const inRange = sentences.filter((s) => {
    const len = codepointLength(s);
    return len >= min && len <= max;
  }).length;
  const lengthCompliance = sentences.length > 0 ? inRange / sentences.length : 0;

  const firstPerson = nonEmpty.filter((r) => r.includes('我')).length;
  const firstPersonRate = firstPerson / nonEmpty.length;
  // 30% 以上回复使用第一人称视为充分，向上封顶
  const firstPersonScore = clamp01(firstPersonRate / 0.3);

  const strongPunct = nonEmpty.filter((r) => /[！？!?]/.test(r)).length;
  const strongPunctRate = strongPunct / nonEmpty.length;
  // 约 20% 回复带强弱标点视为情绪表达达标
  const punctScore = clamp01(strongPunctRate / 0.2);

  const fingerprint = 0.5 * lengthCompliance + 0.25 * firstPersonScore + 0.25 * punctScore;
  const score = clamp01(0.5 * catchphraseCoverage + 0.5 * fingerprint);

  return {
    score,
    hits,
    violations: [],
    detail:
      `口头禅命中 ${hits}/${nonEmpty.length} 条回复；` +
      `句长合规率 ${(lengthCompliance * 100).toFixed(0)}%（期望 ${min}–${max} 字）；` +
      `第一人称使用率 ${(firstPersonRate * 100).toFixed(0)}%；` +
      `强弱标点率 ${(strongPunctRate * 100).toFixed(0)}%`,
  };
}

/**
 * 情绪标注准确率：逐位比对，长度不等时按较短对齐并忽略多余部分。
 * 期望为空视为「无要求」记满分。
 */
export function measureEmotionAccuracy(
  expected: readonly Emotion[],
  actual: readonly Emotion[],
): number {
  if (expected.length === 0) return 1;
  const aligned = Math.min(expected.length, actual.length);
  if (aligned === 0) return 0;
  let correct = 0;
  for (let i = 0; i < aligned; i += 1) {
    if (expected[i] === actual[i]) correct += 1;
  }
  // 缺失的期望位一律计为不匹配（按完整 expected 作分母，避免靠截断蒙混过关）
  return clamp01(correct / expected.length);
}

/**
 * 固定剧本对话：>=12 轮中文输入 + 期望情绪，用于可复现回归。
 * 覆盖全部 8 种情绪标签，顺序稳定。
 */
export function scriptedConversation(): readonly ScriptedTurn[] {
  const script: readonly ScriptedTurn[] = [
    { user: '你好，能告诉我你是谁吗？', expectEmotion: 'calm' },
    { user: '这案子终于有进展了，太好了！', expectEmotion: 'joyful' },
    { user: '别过来……你手里拿的是什么？', expectEmotion: 'fearful' },
    { user: '我怀疑你在隐瞒什么，说实话。', expectEmotion: 'suspicious' },
    { user: '那天晚上你到底在哪里？', expectEmotion: 'tense' },
    { user: '她就这样走了，再也没回来。', expectEmotion: 'sorrowful' },
    { user: '你竟敢骗我！我把你当朋友！', expectEmotion: 'furious' },
    { user: '没关系，慢慢说，我听着呢。', expectEmotion: 'tender' },
    { user: '线索都指向同一个人，你承认吧。', expectEmotion: 'suspicious' },
    { user: '深呼吸，我们把时间线重新捋一遍。', expectEmotion: 'calm' },
    { user: '真相快浮出水面了，我有点激动！', expectEmotion: 'joyful' },
    { user: '再不走就来不及了，快！', expectEmotion: 'tense' },
    { user: '他低下头，眼泪掉了下来。', expectEmotion: 'sorrowful' },
    { user: '谢谢你一直陪着我查下去。', expectEmotion: 'tender' },
  ];
  // 自检：所有期望情绪都必须是合法标签
  for (const turn of script) {
    if (!EMOTIONS.includes(turn.expectEmotion)) {
      throw new Error(`剧本包含非法情绪: ${turn.expectEmotion}`);
    }
  }
  return script;
}