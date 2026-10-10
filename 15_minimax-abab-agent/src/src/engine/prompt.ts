/**
 * 系统提示词构造：把人格、剧本与当前状态全部写进中文提示词。
 * 注意：`（id：…）` 与 `口头禅：…` 是机器可读标记，MiniMaxClient 的离线降级路径
 * 依赖它们从 messages 反解析人格指纹——改格式等于改契约。
 */

import { EMOTIONS, EMOTION_LABELS } from '../core/types.js';
import type { DramaState, Persona, Screenplay, ScenePhase } from '../core/types.js';

const PHASE_LABELS: Readonly<Record<ScenePhase, string>> = {
  intro: '开场：初次接触',
  exploration: '探索：交换观察',
  'cross-examination': '质询：时间线对撞',
  confrontation: '对峙：证据摊牌',
  resolution: '收束：真相落定',
};

/**
 * 构造注入模型的系统提示词。
 * seed 参数让不同会话种子的提示词指纹不同，从而驱动离线语料选句差异（评测要求）。
 */
export function buildSystemPrompt(
  persona: Persona,
  screenplay: Screenplay,
  state: DramaState,
  seed: number = 0,
): string {
  const emotionLabels = persona.emotionalRange.map((e) => EMOTION_LABELS[e]).join('、');
  const allowedEmotions = persona.emotionalRange.map((e) => `${e}（${EMOTION_LABELS[e]}）`).join('、');
  const facts = Object.entries(persona.facts).map(([k, v]) => `${k}：${v}`).join('\n');
  const clues = state.revealedClueIds.length === 0
    ? '（尚未掌握任何线索）'
    : state.revealedClueIds
        .map((id) => {
          const clue = screenplay.clues.find((c) => c.id === id);
          return clue ? `${clue.title}——${clue.detail}` : id;
        })
        .join('\n');
  const suspects = screenplay.suspects.map((s) => `${s.name}（动机：${s.motive}）`).join('、');
  const catchphrases = persona.catchphrases.join('、');
  const taboos = persona.taboos.map((t) => `- ${t}`).join('\n');
  const phaseLabel = PHASE_LABELS[state.phase];

  return [
    '你是沉浸式互动推理剧的扮演者，以下信息构成你唯一允许引用的世界：',
    '',
    `人格：${persona.name}（id：${persona.id}）——${persona.tagline}`,
    `人物小传：${persona.biography}`,
    `说话风格：${persona.speechStyle}`,
    `口头禅：${catchphrases}`,
    `禁忌：\n${taboos}`,
    `允许的情绪：${allowedEmotions}`,
    `情绪范围：${emotionLabels}`,
    '',
    `剧本：《${screenplay.title}》——${screenplay.synopsis}`,
    `嫌疑人：${suspects}`,
    '关键事实：',
    facts,
    '',
    `当前阶段：${phaseLabel}`,
    `当前亲密度：${state.trust}`,
    `当前紧张度：${state.tension}`,
    `已获线索：\n${clues}`,
    `会话种子：${seed}`,
    '',
    '输出要求：',
    `1. 始终以 ${persona.name} 的身份、口吻与情绪范围回答，禁止跳出角色。`,
    '2. 回答控制在 20–120 个汉字。',
    '3. 你必须在回复末尾另起标记输出 `（语气：X）`，X 从下列中文标签中选一个：' +
      `${EMOTIONS.map((e) => EMOTION_LABELS[e]).join('/')}。`,
    '4. 严格遵守上述禁忌，绝不出现被禁止的表述。',
  ].join('\n');
}