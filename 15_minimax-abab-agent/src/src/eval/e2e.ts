/**
 * 端到端音频锚定（SLICE D / eval）。
 *
 * 设计契约：
 * 1. 全程离线确定性：MiniMaxClient 以 forceOffline 构造（mode='mock'），逐字节可复现。
 * 2. 「情绪真的影响波形」用同一探针文本、仅切换 perEmotion 语音参数来证明——
 *    若只是贴标签，各情绪音频会相同。
 * 3. 时长锚定用三组不同长度文本，断言 durationMs / byteLength 随文本长度单调不减。
 *
 * 依赖方向：eval → engine/minimax/core，绝不反向。parseWavHeader 由 minimax 切片提供。
 */

import { SCENE_PHASE_ORDER } from '../core/contracts.js';
import type { ScenePhase } from '../core/types.js';
import type { Emotion, Persona, Screenplay, SpeechResult } from '../core/types.js';
import { resolveVoiceSettings } from '../core/types.js';
import { loadConfig } from '../core/config.js';
import { MiniMaxClient } from '../minimax/index.js';
import { parseWavHeader } from '../minimax/mock-audio.js';
import { DramaEngine } from '../engine/index.js';
import { scriptedConversation } from './consistency.js';

/** 运行端到端场景所需的注入项。persona/screenplay 由 runner 或测试提供。 */
export interface E2EScenarioOptions {
  readonly persona: Persona;
  readonly screenplay: Screenplay;
  /** 注入时钟，保证「端到端耗时」可复现 */
  readonly now?: () => number;
  readonly seed?: number;
}

/** 单轮观测（开场记为第 0 轮）。 */
export interface E2ERoundObservation {
  readonly index: number;
  readonly userText: string;
  readonly personaText: string;
  readonly textLength: number;
  readonly emotion: Emotion | null;
  readonly audioBytes: number;
  readonly mimeType: string;
  readonly durationMs: number;
  readonly phase: ScenePhase;
  readonly trust: number;
  readonly tension: number;
  readonly degraded: boolean;
  /** WAV 头能否被 parseWavHeader 解析（不抛异常且返回对象） */
  readonly wavHeaderOk: boolean;
}

/** 情绪波形探针：同一文本、不同情绪语音参数的产出。 */
export interface EmotionWaveformProbe {
  readonly emotion: Emotion;
  readonly audioBytes: number;
  readonly durationMs: number;
  readonly mimeType: string;
  /** 前 200 字节的十六进制，用于「不同情绪 → 不同波形」的锚定 */
  readonly firstBytesHex: string;
}

/** 时长锚定样本。 */
export interface DurationAnchor {
  readonly textLength: number;
  readonly durationMs: number;
  readonly audioBytes: number;
}

export interface E2EScenarioResult {
  readonly personaId: string;
  readonly screenplayId: string;
  readonly mode: 'live' | 'mock';
  readonly rounds: readonly E2ERoundObservation[];
  readonly phaseTrace: readonly ScenePhase[];
  readonly trustTrace: readonly number[];
  readonly tensionTrace: readonly number[];
  readonly degradationCount: number;
  readonly durationMs: number;
  readonly emotionWaveforms: readonly EmotionWaveformProbe[];
  readonly durationAnchors: readonly DurationAnchor[];
  /** 全部音频 mimeType 是否一致（mock 应为同一种，例如 audio/wav） */
  readonly mimeTypeConsistent: boolean;
}

const codepoints = (text: string): number => [...text].length;

/** 前 n 个码点作为探针文本，保证长度可比较且确定性。 */
function probeText(length: number): string {
  const base = '这是一段用于端到端音频锚定评测的固定中文文本，情绪与时长都将据此进行确定性验证，绝不依赖任何外部网络。';
  const chars = [...base];
  const out: string[] = [];
  for (let i = 0; i < length; i += 1) out.push(chars[i % chars.length] as string);
  return out.join('');
}

/** 前 n 字节的十六进制字符串（不足 n 则取全部）。 */
function firstBytesHex(bytes: Uint8Array, n: number): string {
  const slice = bytes.subarray(0, Math.min(n, bytes.byteLength));
  let hex = '';
  for (const b of slice) hex += b.toString(16).padStart(2, '0');
  return hex;
}

/** 安全调用 parseWavHeader：返回 true 表示成功解析出对象，false 表示抛异常或返回空。 */
function wavHeaderOk(audio: Uint8Array): boolean {
  try {
    const header: unknown = parseWavHeader(audio);
    return header !== null && header !== undefined;
  } catch {
    return false;
  }
}

const phaseIndex = (phase: ScenePhase): number => {
  const idx = SCENE_PHASE_ORDER.indexOf(phase);
  return idx < 0 ? 0 : idx;
};

/**
 * 跑完整端到端场景：开场 → 12 轮剧本对话，采集全部锚定所需观测。
 */
export async function runEndToEndScenario(options: E2EScenarioOptions): Promise<E2EScenarioResult> {
  const { persona, screenplay } = options;
  const now = options.now ?? (() => 0);
  const started = now();

  const config = loadConfig({ MINIMAX_API_KEY: '' }, { forceOffline: true });
  const client = new MiniMaxClient({ config });
  const engine = new DramaEngine({ persona, screenplay, client, now, seed: options.seed });

  const rounds: E2ERoundObservation[] = [];
  const phaseTrace: ScenePhase[] = [];
  const trustTrace: number[] = [];
  const tensionTrace: number[] = [];

  const record = (index: number, userText: string, personaText: string, speech: SpeechResult, emotion: Emotion | null, phase: ScenePhase, trust: number, tension: number, degraded: boolean): void => {
    rounds.push({
      index,
      userText,
      personaText,
      textLength: codepoints(personaText),
      emotion,
      audioBytes: speech.audio.byteLength,
      mimeType: speech.mimeType,
      durationMs: speech.durationMs,
      phase,
      trust,
      tension,
      degraded,
      wavHeaderOk: wavHeaderOk(speech.audio),
    });
    phaseTrace.push(phase);
    trustTrace.push(trust);
    tensionTrace.push(tension);
  };

  // 开场
  const opening = await engine.start();
  record(0, '', opening.turn.text, opening.speech, opening.turn.emotion, opening.state.phase, opening.state.trust, opening.state.tension, opening.degraded);

  // 12 轮剧本对话
  const script = scriptedConversation().slice(0, 12);
  let lastPhase = opening.state.phase;
  for (let i = 0; i < script.length; i += 1) {
    const turn = script[i]!;
    const res = await engine.send({ sessionId: opening.state.sessionId, userText: turn.user });
    // 阶段只进不退：取引擎给出的与上一步之间的「较大者」不参与判定，这里如实记录引擎状态
    lastPhase = res.state.phase;
    record(i + 1, turn.user, res.turn.text, res.speech, res.turn.emotion, lastPhase, res.state.trust, res.state.tension, res.degraded);
  }

  // 情绪波形探针：同一文本，切换 persona.voice.perEmotion → 不同语音参数
  const probe = probeText(40);
  const emotionWaveforms: EmotionWaveformProbe[] = [];
  for (const emotion of persona.emotionalRange) {
    const settings = resolveVoiceSettings(persona.voice, emotion);
    const speech = await client.speech(probe, settings, emotion);
    emotionWaveforms.push({
      emotion,
      audioBytes: speech.audio.byteLength,
      durationMs: speech.durationMs,
      mimeType: speech.mimeType,
      firstBytesHex: firstBytesHex(speech.audio, 200),
    });
  }

  // 时长锚定：三组递增长度的文本，期望 durationMs/byteLength 单调不减
  const anchorSettings = resolveVoiceSettings(persona.voice, 'calm');
  const durationAnchors: DurationAnchor[] = [];
  for (const length of [8, 40, 96]) {
    const text = probeText(length);
    const speech = await client.speech(text, anchorSettings, 'calm');
    durationAnchors.push({
      textLength: codepoints(text),
      durationMs: speech.durationMs,
      audioBytes: speech.audio.byteLength,
    });
  }

  const mimeTypes = new Set<string>([
    ...rounds.map((r) => r.mimeType),
    ...emotionWaveforms.map((w) => w.mimeType),
  ]);

  return {
    personaId: persona.id,
    screenplayId: screenplay.id,
    mode: client.mode,
    rounds,
    phaseTrace,
    trustTrace,
    tensionTrace,
    degradationCount: client.degradations().length,
    durationMs: now() - started,
    emotionWaveforms,
    durationAnchors,
    mimeTypeConsistent: mimeTypes.size <= 1,
  };
}

/** 供 runner 复用：阶段轨迹是否严格单调不后退。 */
export function isPhaseMonotonic(trace: readonly ScenePhase[]): boolean {
  for (let i = 1; i < trace.length; i += 1) {
    if (phaseIndex(trace[i] as ScenePhase) < phaseIndex(trace[i - 1] as ScenePhase)) return false;
  }
  return true;
}

/** 供 runner 复用：时长锚定是否随文本长度单调不减。 */
export function areDurationAnchorsMonotonic(anchors: readonly DurationAnchor[]): boolean {
  const sorted = [...anchors].sort((a, b) => a.textLength - b.textLength);
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i]!.durationMs < sorted[i - 1]!.durationMs) return false;
    if (sorted[i]!.audioBytes < sorted[i - 1]!.audioBytes) return false;
  }
  return true;
}

/** 供 runner 复用：不同情绪的音频前缀是否互不相同（情绪真正影响波形）。 */
export function emotionWaveformsDistinct(waveforms: readonly EmotionWaveformProbe[]): boolean {
  if (waveforms.length < 2) return waveforms.length === 1;
  const prefixes = new Set(waveforms.map((w) => w.firstBytesHex));
  return prefixes.size === waveforms.length;
}

// ScenePhase 类型在文件内被使用，显式引用避免未使用告警。
export type { ScenePhase };