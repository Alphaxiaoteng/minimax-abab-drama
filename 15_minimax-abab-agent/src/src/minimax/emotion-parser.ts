/**
 * 情绪标记解析器：从模型回复中提取（语气：X）/[emotion:X]/情绪：X 标记，
 * 退化为中文关键词打分，全部落空回落到调用方建议值。
 */

import { EMOTIONS, EMOTION_LABELS } from '../core/types.js';
import type { Emotion } from '../core/types.js';

/** 中文情绪词 → 英文情绪键（由 EMOTION_LABELS 反查，保证单一事实来源） */
const LABEL_TO_EMOTION: Readonly<Record<string, Emotion>> = (() => {
  const map: Record<string, Emotion> = {};
  for (const emotion of EMOTIONS) {
    map[EMOTION_LABELS[emotion]] = emotion;
    map[emotion] = emotion;
  }
  return map;
})();

/** 情绪 → 中文提示关键词表，每种情绪 ≥ 4 个 */
export const EMOTION_KEYWORDS: Readonly<Record<Emotion, readonly string[]>> = {
  calm: ['平静', '冷静', '慢慢说', '不必急', '别急', '稳住', '如实'],
  joyful: ['哈哈', '高兴', '开心', '有趣', '好消息', '忍不住笑', '妙极'],
  tense: ['紧张', '慌乱', '发颤', '冷汗', '咽了一下', '坐立不安', '手在抖'],
  sorrowful: ['难过', '悲恸', '落泪', '哀', '心痛', '哭', '再也'],
  furious: ['愤怒', '怒火', '咆哮', '拍案', '滚出去', '荒唐', '闭嘴'],
  fearful: ['害怕', '恐惧', '发抖', '不敢', '后怕', '别过来', '逃'],
  suspicious: ['怀疑', '可疑', '真的吗', '对不上', '撒谎', '破绽', '口径'],
  tender: ['温柔', '放心', '我信', '陪你', '依你', '轻声', '别怕'],
};

const FULL_WIDTH_PATTERN = /（语气：\s*([^（）]{1,8})\s*）/g;
const SQUARE_PATTERN = /\[emotion:\s*([^\]\s]{1,16})\s*\]/gi;
const PLAIN_PATTERN = /情绪：\s*([^，。；！？\s]{1,8})/g;

function lookupToken(token: string): Emotion | null {
  const trimmed = token.trim();
  return LABEL_TO_EMOTION[trimmed] ?? LABEL_TO_EMOTION[trimmed.toLowerCase()] ?? null;
}

/** 依次尝试三种标记；未识别的标记内容继续走关键词打分 */
function matchMarker(text: string): Emotion | null {
  const patterns = [FULL_WIDTH_PATTERN, SQUARE_PATTERN, PLAIN_PATTERN];
  for (const pattern of patterns) {
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      const token = match[1];
      if (token === undefined) continue;
      const found = lookupToken(token);
      if (found) return found;
    }
  }
  return null;
}

function scoreByKeywords(text: string): Emotion | null {
  let best: Emotion | null = null;
  let bestScore = 0;
  for (const emotion of EMOTIONS) {
    const words = EMOTION_KEYWORDS[emotion];
    let score = 0;
    for (const word of words) {
      if (text.includes(word)) score += 1;
    }
    // 并列时取 EMOTIONS 声明顺序靠前者，保证确定性
    if (score > bestScore) {
      best = emotion;
      bestScore = score;
    }
  }
  return best;
}

/**
 * 从文本解析情绪。
 * 优先匹配（语气：X）/[emotion:X]/情绪：X 标记，其次关键词表打分，全部落空返回 fallback。
 */
export function parseEmotion(text: string, fallback: Emotion): Emotion {
  const marked = matchMarker(text);
  if (marked) return marked;
  const scored = scoreByKeywords(text);
  return scored ?? fallback;
}

/** 清除三种情绪标记，返回可直接交给 TTS 的干净文本 */
export function stripEmotionMarkers(text: string): string {
  return text
    .replace(FULL_WIDTH_PATTERN, '')
    .replace(SQUARE_PATTERN, '')
    .replace(PLAIN_PATTERN, '')
    .trim();
}

/** 中文情绪标签 → Emotion 的反查表（仅中文标签），供 director/client 提取情绪标记复用 */
export const EMOTION_LABEL_TO_KEY: Readonly<Record<string, Emotion>> = (() => {
  const map: Record<string, Emotion> = {};
  for (const emotion of EMOTIONS) {
    map[EMOTION_LABELS[emotion]] = emotion;
  }
  return Object.freeze(map);
})();
