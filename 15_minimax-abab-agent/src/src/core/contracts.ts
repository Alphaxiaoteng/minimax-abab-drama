/**
 * ============================================================================
 *  冻结契约：模块公共 API 拓扑
 * ----------------------------------------------------------------------------
 *  本文件**不导出任何运行时代码**，只用于在编译期锁定切片之间的函数签名，
 *  使并行开发的多份实现无法漂移。所有类型均为 `import type`，运行时零成本。
 *
 *  依赖方向（严禁反向依赖，否则评测报告会出现循环）：
 *
 *    core/*            ← 无内部依赖，只依赖 node/浏览器标准库
 *    personas/*        ← core/types
 *    minimax/*         ← core/*
 *    engine/*          ← core/*, minimax/*, personas/*
 *    eval/*            ← core/*, engine/*, personas/*, minimax/*
 *    server/*, ui/*    ← engine/*, eval/*, personas/*, minimax/*
 * ============================================================================
 */

import type { AgentConfig, ConfigOverrides } from './config.js';
import type { MiniMaxTransport } from './types.js';
import type {
  DialogueTurn,
  DramaEvent,
  DramaState,
  Emotion,
  Persona,
  ScenePhase,
  Screenplay,
  SpeechResult,
  TextResult,
  VoiceSettings,
} from './types.js';

/* ------------------------------ minimax/client ----------------------------- */

export interface MiniMaxClientOptions {
  readonly config: AgentConfig;
  /** 允许注入 fake/HTTP 传输层；不传则按 config.mode 自动选择 */
  readonly transport?: MiniMaxTransport;
  /** 降级回调，UI 可据此提示「已切换离线语料」 */
  readonly onDegrade?: (notice: { reason: string; message: string; at: number }) => void;
}

export interface MiniMaxClientLike {
  readonly mode: 'live' | 'mock';
  /** 文本续写；transport 失败时内部自动降级为确定性语料，绝不抛出 TransportError */
  chat(messages: readonly { role: 'system' | 'user' | 'assistant'; content: string }[], fallbackEmotion?: Emotion): Promise<TextResult>;
  /** 语音合成；失败时降级为确定性 WAV */
  speech(text: string, settings: VoiceSettings, fallbackEmotion?: Emotion): Promise<SpeechResult>;
  /** 已发生的降级记录，报告直接读取 */
  degradations(): readonly { reason: string; message: string; at: number }[];
}

/* -------------------------------- engine ---------------------------------- */

export interface DialogueRequest {
  readonly sessionId: string;
  readonly userText: string;
}

export interface DialogueResponse {
  readonly turn: DialogueTurn;
  readonly speech: SpeechResult;
  readonly state: DramaState;
  readonly events: readonly DramaEvent[];
  /** 本轮是否发生了真实→mock 降级 */
  readonly degraded: boolean;
}

export interface EngineOptions {
  readonly persona: Persona;
  readonly screenplay: Screenplay;
  readonly client: MiniMaxClientLike;
  /** 注入时钟，保证评测可复现 */
  readonly now?: () => number;
  readonly seed?: number;
}

export interface DramaEngineLike {
  readonly state: DramaState;
  start(): Promise<DialogueResponse>;
  send(input: DialogueRequest): Promise<DialogueResponse>;
  events(): readonly DramaEvent[];
}

/* --------------------------------- eval ----------------------------------- */

export interface RubricDimension {
  readonly id: string;
  readonly name: string;
  readonly weight: number;
  readonly score: number; // 0–1
  readonly detail: string;
}

export interface EvalReport {
  readonly suiteName: string;
  readonly startedAt: number;
  readonly durationMs: number;
  readonly overall: number;
  readonly passed: boolean;
  readonly dimensions: readonly RubricDimension[];
  readonly cases: readonly EvalCaseResult[];
  readonly degradations: readonly string[];
}

export interface EvalCaseResult {
  readonly id: string;
  readonly passed: boolean;
  readonly score: number;
  readonly expected: string;
  readonly actual: string;
  readonly note?: string;
}

/* --------------------------------- personas -------------------------------- */

export interface PersonaRegistry {
  readonly all: readonly Persona[];
  byId(id: string): Persona;
  ids(): readonly string[];
}

/* --------------------------------- server ---------------------------------- */

export interface ServerHandle {
  readonly port: number;
  readonly url: string;
  close(): Promise<void>;
}

export interface ServerOptions {
  readonly port: number;
  readonly host?: string;
  readonly overrides?: ConfigOverrides;
}

/** 供 UI/测试复用的场景枚举，避免前后端各写一份 */
export const SCENE_PHASE_ORDER: readonly ScenePhase[] = [
  'intro',
  'exploration',
  'cross-examination',
  'confrontation',
  'resolution',
];
