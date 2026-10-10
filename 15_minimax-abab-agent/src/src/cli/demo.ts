/**
 * 一键演示：在终端跑完整一局推理剧（≥6 轮脚本化输入）。
 * 用法：npx tsx src/cli/demo.ts [personaId]
 * 全程强制离线 mock（空 Key + forceOffline）：不读真实凭证、不发真实请求，
 * 输出逐字节可复现。
 */

import { loadConfig } from '../core/config.js';
import { EMOTION_LABELS } from '../core/types.js';
import type { Emotion, ScenePhase } from '../core/types.js';
import type { DialogueResponse } from '../core/contracts.js';
import {
  DramaEngine,
  MiniMaxClient,
  defaultScreenplay,
  personaRegistry,
} from '../index.js';

/** ANSI 调色板（终端彩色播报） */
const C = {
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  reset: '\x1b[0m',
  player: '\x1b[36m',   // 青：玩家
  persona: '\x1b[38;5;220m', // 金：人物
  sys: '\x1b[32m',
  warn: '\x1b[31m',
} as const;

const PHASE_LABELS: Record<ScenePhase, string> = {
  intro: '开场',
  exploration: '探索',
  'cross-examination': '交叉质询',
  confrontation: '对质',
  resolution: '终局',
};

/** 脚本化输入：覆盖试探、指控、共情三类动作，足够推进 6 轮以上 */
const SCRIPTED_INPUTS: readonly string[] = [
  '案发当晚，你在书房听到了什么动静？',
  '账簿少了三页，这和你前夜的争吵有关吗？',
  '别绕开话题——那三页记的是谁的名字？',
  '如果真凶另有其人，你为什么要替 TA 遮掩？',
  '我查过汇款单了，收款人是你的亲属，对吗？',
  '现在说出来还来得及，我会替你求一份从轻。',
  '最后问你一次：那晚书房里的烛火是谁吹灭的？',
];

function rule(): void {
  console.log(`${C.dim}${'─'.repeat(58)}${C.reset}`);
}

/** 播报一轮：玩家输入 + 人物台词 + 情绪标签 + 音频字节数/时长 */
function announce(round: number, resp: DialogueResponse, userText: string, personaName: string): void {
  const { turn, speech } = resp;
  const emotionChip = turn.emotion !== null
    ? `${EMOTION_LABELS[turn.emotion as Emotion] ?? turn.emotion}`
    : '—';
  const seconds = (speech.durationMs / 1000).toFixed(1);
  console.log(`\n${C.bold}第 ${round} 轮${C.reset} ${C.dim}· 阶段：${PHASE_LABELS[resp.state.phase]}${C.reset}`);
  console.log(`${C.player}玩家│${userText}${C.reset}`);
  console.log(`${C.persona}${personaName}│${turn.text}${C.reset}`);
  console.log(`${C.dim}     情绪：${emotionChip} · 音频：${speech.audio.byteLength} 字节 · 时长 ${seconds}s · 来源 ${speech.source}${resp.degraded ? '（已降级）' : ''}${C.reset}`);
}

async function main(): Promise<void> {
  const personaId = process.argv[2] ?? 'shen-yan';
  let persona;
  try {
    persona = personaRegistry.byId(personaId);
  } catch {
    console.error(`${C.warn}未知人物 ID：${personaId}${C.reset}`);
    console.error(`可选：${personaRegistry.ids().join(' / ')}`);
    process.exit(1);
  }

  const config = loadConfig({ MINIMAX_API_KEY: '' }, { forceOffline: true });
  const client = new MiniMaxClient({ config });
  const engine = new DramaEngine({ persona, screenplay: defaultScreenplay, client });

  console.log(`${C.bold}沉浸式互动推理剧 · 终端演示${C.reset}`);
  console.log(`${C.dim}剧本：《${defaultScreenplay.title}》 · 人物：${persona.name}（${persona.tagline}） · 模式：${client.mode}${C.reset}`);
  rule();

  const opening = await engine.start();
  announce(1, opening, '（开场）', persona.name);

  let resp = opening;
  let round = 1;
  for (const text of SCRIPTED_INPUTS) {
    if (resp.state.ended) break;
    round += 1;
    resp = await engine.send({ sessionId: opening.state.sessionId, userText: text });
    announce(round, resp, text, persona.name);
  }

  const final = engine.state;
  const revealed = final.revealedClueIds
    .map((id) => defaultScreenplay.clues.find((c) => c.id === id)?.title ?? id)
    .join(' / ');
  const rounds = final.turns.filter((t) => t.role === 'user').length;
  const bar = (value: number): string => {
    const filled = Math.round(value / 5);
    return `${'█'.repeat(filled)}${'░'.repeat(20 - filled)}`;
  };

  console.log(`\n${C.sys}${C.bold}══ 终局汇总 ══${C.reset}`);
  console.log(`${C.sys}阶段        ${C.reset}${PHASE_LABELS[final.phase]}（${final.phase}）`);
  console.log(`${C.sys}亲密度      ${C.reset}${bar(final.trust)} ${final.trust}/100`);
  console.log(`${C.sys}紧张度      ${C.reset}${bar(final.tension)} ${final.tension}/100`);
  console.log(`${C.sys}已获线索    ${C.reset}${revealed.length > 0 ? `${final.revealedClueIds.length} 条：${revealed}` : '无'}`);
  console.log(`${C.sys}完成轮次    ${C.reset}${rounds} 轮`);
  console.log(`${C.sys}降级次数    ${C.reset}${client.degradations().length}`);
  console.log(`${C.sys}事件总数    ${C.reset}${engine.events().length}`);
  console.log(`${C.sys}是否结束    ${C.reset}${final.ended ? '是' : '否'}`);
  rule();
}