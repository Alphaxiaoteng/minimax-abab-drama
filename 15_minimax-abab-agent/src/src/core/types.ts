/**
 * ============================================================================
 *  冻结契约（FROZEN CONTRACT）
 * ----------------------------------------------------------------------------
 *  本文件是全部切片之间的唯一接口事实来源。任何人修改此处必须同步更新
 *  docs/ARCHITECTURE.md 与所有调用方，禁止在其它模块内重新定义同名结构。
 * ============================================================================
 */

import type { TransportError } from './errors.js';

/* -------------------------------------------------------------------------- */
/* 1. 情绪与语音                                                              */
/* -------------------------------------------------------------------------- */

/** 全局情绪标签集。新增标签必须同步 persona 语音映射与评分器。 */
export const EMOTIONS = [
  'calm', // 平静
  'joyful', // 欢愉
  'tense', // 紧张
  'sorrowful', // 悲恸
  'furious', // 暴怒
  'fearful', // 惊惧
  'suspicious', // 狐疑
  'tender', // 温柔（亲密人格专用）
] as const;

export type Emotion = (typeof EMOTIONS)[number];

/** 情绪 → 中文标签，用于 UI 与报告展示 */
export const EMOTION_LABELS: Readonly<Record<Emotion, string>> = {
  calm: '平静',
  joyful: '欢愉',
  tense: '紧张',
  sorrowful: '悲恸',
  furious: '暴怒',
  fearful: '惊惧',
  suspicious: '狐疑',
  tender: '温柔',
};

/**
 * 语音合成参数（MiniMax T2A v2 协议子集）。
 * 所有数值必须落在 VOICE_RANGES 之内，否则由 client 抛 ValidationError。
 */
export interface VoiceSettings {
  /** 音色 ID，例如 'female-shaonv'；mock 模式下不校验存在性 */
  readonly voiceId: string;
  /** 语速倍率 0.5–2.0 */
  readonly speed: number;
  /** 音量 0.1–10.0 */
  readonly vol: number;
  /** 音调偏移 -12–12 */
  readonly pitch: number;
  /** 情绪倾向，T2A v2 的 emotion 字段 */
  readonly emotion: Emotion;
}

/** 人格定义的语音方案：基准参数 + 每情绪覆盖项 */
export interface VoiceProfile {
  readonly base: VoiceSettings;
  readonly perEmotion: Readonly<Partial<Record<Emotion, Partial<VoiceSettings>>>>;
}

/** 解析最终语音参数：base 叠加情绪覆盖，再夹紧到合法区间 */
export function resolveVoiceSettings(profile: VoiceProfile, emotion: Emotion): VoiceSettings {
  const override = profile.perEmotion[emotion] ?? {};
  return {
    voiceId: override.voiceId ?? profile.base.voiceId,
    speed: clampRange(override.speed ?? profile.base.speed, 0.5, 2.0),
    vol: clampRange(override.vol ?? profile.base.vol, 0.1, 10.0),
    pitch: clampRange(override.pitch ?? profile.base.pitch, -12, 12),
    emotion,
  };
}

export function clampRange(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/* -------------------------------------------------------------------------- */
/* 2. 人格（Persona）                                                          */
/* -------------------------------------------------------------------------- */

export interface PersonaTurn {
  readonly role: 'user' | 'persona';
  readonly text: string;
  /** 该轮被标注的情绪，供画像一致性评测使用 */
  readonly emotion?: Emotion;
}

export interface Persona {
  readonly id: string;
  readonly name: string;
  /** 一句话身份，展示在 UI 头像下方 */
  readonly tagline: string;
  /** 人物小传，注入系统提示词 */
  readonly biography: string;
  /** 说话风格约束（句长、口头禅、禁忌词） */
  readonly speechStyle: string;
  /** 该人格允许表达的情绪集合 */
  readonly emotionalRange: readonly Emotion[];
  /** 口头禅 / 语言指纹，评分器据此判定人格一致性 */
  readonly catchphrases: readonly string[];
  /** 明确禁止出现的行为或词语，命中即扣分 */
  readonly taboos: readonly string[];
  readonly voice: VoiceProfile;
  /** 开场地道白，用于 UI 初始化 */
  readonly openingLine: string;
  /** 剧本关键事实：驱动纠错与一致性断言 */
  readonly facts: Readonly<Record<string, string>>;
}

/* -------------------------------------------------------------------------- */
/* 3. 剧本（Screenplay）：推理剧状态机                                         */
/* -------------------------------------------------------------------------- */

/** 剧情阶段。顺序即推进方向，不允许回退（除 retry） */
export const SCENE_PHASES = ['intro', 'exploration', 'cross-examination', 'confrontation', 'resolution'] as const;
export type ScenePhase = (typeof SCENE_PHASES)[number];

export interface Clue {
  readonly id: string;
  readonly title: string;
  readonly detail: string;
  /** 触发该线索所需的最小亲密度 */
  readonly requiredTrust: number;
  /** 该线索指向的嫌疑人 ID */
  readonly implicates: string;
}

export interface Suspect {
  readonly id: string;
  readonly name: string;
  /** 动机，曝光后用于终局判定 */
  readonly motive: string;
  /** 是否真凶。剧本必须且仅有一个 true */
  readonly isCulprit: boolean;
}

export interface Screenplay {
  readonly id: string;
  readonly title: string;
  readonly synopsis: string;
  readonly phases: readonly ScenePhase[];
  readonly clues: readonly Clue[];
  readonly suspects: readonly Suspect[];
  readonly culpritId: string;
  /** 阶段推进所需的亲密度阈值，键为阶段名 */
  readonly phaseGates: Readonly<Record<ScenePhase, number>>;
}

/* -------------------------------------------------------------------------- */
/* 4. 会话与导演机状态                                                         */
/* -------------------------------------------------------------------------- */

export interface DialogueTurn {
  readonly id: string;
  readonly role: 'user' | 'persona' | 'narrator';
  readonly text: string;
  readonly emotion: Emotion | null;
  readonly at: number;
}

export interface DramaState {
  readonly sessionId: string;
  readonly personaId: string;
  readonly screenplayId: string;
  readonly phase: ScenePhase;
  /** 0–100，玩家与人格的信任度 */
  readonly trust: number;
  /** 0–100，已被玩家掌握的线索强度 */
  readonly tension: number;
  readonly revealedClueIds: readonly string[];
  readonly turns: readonly DialogueTurn[];
  readonly ended: boolean;
}

export type DramaEventType =
  | 'session_started'
  | 'turn_appended'
  | 'clue_revealed'
  | 'phase_advanced'
  | 'stage_direction'
  | 'degraded'
  | 'session_ended';

export interface DramaEvent {
  readonly type: DramaEventType;
  readonly at: number;
  readonly payload: Readonly<Record<string, unknown>>;
}

/* -------------------------------------------------------------------------- */
/* 5. 传输层结果与错误兜底                                                     */
/* -------------------------------------------------------------------------- */

export interface ChatMessage {
  readonly role: 'system' | 'user' | 'assistant';
  readonly content: string;
}

export interface TextResult {
  readonly text: string;
  /** 从文本中解析出的情绪标签；解析失败则回落到调用方建议值 */
  readonly emotion: Emotion;
  readonly source: 'live' | 'mock';
  readonly latencyMs: number;
}

export interface SpeechResult {
  /** 解码后的音频字节（真实为 MP3，mock 为确定性合成 WAV） */
  readonly audio: Uint8Array;
  readonly mimeType: string;
  readonly durationMs: number;
  readonly settings: VoiceSettings;
  readonly source: 'live' | 'mock';
  readonly latencyMs: number;
}

/** 统一的降级原因，评测报告直接引用 */
export type DegradationReason = 'no_credential' | 'forced_offline' | 'transport_failure' | 'upstream_error';

export interface DegradationNotice {
  readonly reason: DegradationReason;
  readonly message: string;
  readonly at: number;
}

/* -------------------------------------------------------------------------- */
/* 6. MiniMax 传输层接口（唯一外呼边界，可被 fake 替换）                        */
/* -------------------------------------------------------------------------- */

export interface TextRequest {
  readonly messages: readonly ChatMessage[];
  readonly model: string;
  readonly temperature: number;
  readonly maxTokens: number;
}

export interface SpeechRequest {
  readonly text: string;
  readonly model: string;
  readonly settings: VoiceSettings;
}

/**
 * 传输层只负责「把请求变成字节」，不做降级决策、不做重试。
 * 降级与重试由 MiniMaxClient 负责，因此这里只允许抛 TransportError / UpstreamError。
 */
export interface MiniMaxTransport {
  readonly kind: 'http' | 'fake';
  chat(request: TextRequest, signal: AbortSignal): Promise<{ body: string; latencyMs: number }>;
  speech(request: SpeechRequest, signal: AbortSignal): Promise<{ body: Uint8Array; latencyMs: number }>;
}

/** 便于测试注入的 fake 行为描述 */
export interface FakeTransportScript {
  /** 前 N 次 chat 调用抛 TransportError，之后成功 */
  readonly chatFailures?: number;
  /** 前 N 次 speech 调用抛 TransportError，之后成功 */
  readonly speechFailures?: number;
  /** 固定延迟（毫秒），用于延迟分布评测 */
  readonly latencyMs?: number;
}

export type { TransportError };
