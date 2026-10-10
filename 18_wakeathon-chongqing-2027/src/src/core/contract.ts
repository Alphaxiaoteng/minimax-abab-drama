/**
 * 冻结接口契约 v0.2 —— 所有模块（智能体 / 视觉 / 评测）共同依赖此文件。
 * 变更此文件必须同步 src/eval/ 下的评测基线。
 */

/** 12 幕演出分镜：Windows 音效 + 场景命令 + 雾灵台词 + 工程说明 */
export interface ScenePlan {
  id: string;
  title: string;
  caption: string;
  effect: SceneEffect;
  sounds: SceneEffect[];
  tone: AgentTone;
  line: string;
  note: string;
}

/** 可下发到视觉引擎的通用场景效果。WebGL 阵营与 DOM 阵营同签名，可互换。 */
export type SceneEffect =
  | { action: "fog"; intensity: number }
  | { action: "skyline"; intensity: number }
  | { action: "dawn"; intensity: number }
  | { action: "fireworks"; intensity: number }
  | { action: "laser"; intensity: number }
  | { action: "drone"; intensity: number }
  | { action: "mascot"; intensity: number }
  | { action: "spotlight"; intensity: number }
  | { action: "confetti"; intensity: number }
  | { action: "glitch"; intensity: number }
  | { action: "shatter"; intensity: number };

export type ActionName = SceneEffect["action"];

/**
 * 渲染阵营：同一份 SceneEffect 流的两种实现。
 * three = WebGL/Three.js 主引擎；css = DOM+Canvas 原生后备引擎（无 WebGL 也能完整演出）。
 */
export interface SceneRenderer {
  readonly kind: "three" | "css";
  apply(effect: SceneEffect): void;
  reset(): void;
  dispose(): void;
}

/** 评测引擎：驱动渲染阵营 + 记录状态，用于客观打分 */
export interface HarnessDriver {
  readonly renderer: SceneRenderer;
  /** 每帧调用：把缓动中的状态推进 dt 秒（确定性，无内部计时器） */
  advance(dt: number): void;
  /** 当前能量场读数：动作名 → 0..1 归一化值 */
  sample(): Record<string, number>;
  dispose(): void;
}

export type EngineKind = "three" | "css";

/* ── Agent 线（src/ai、src/core/events）── */

export type AgentTone = "calm" | "hype" | "poetic" | "warn";

/** 智能体对一条意图的结构化回答：语言 + 视觉 + 音效 */
export interface AgentReply {
  utterance: { text: string; tone: AgentTone };
  commands: SceneEffect[];
  sounds: SceneEffect[];
}

export interface AgentAdapter {
  readonly name: string;
  respond(intent: string): Promise<AgentReply>;
  onWakeMoment(): Promise<AgentReply>;
}

export type EventMap = {
  "countdown:tick": { remainingMs: number };
  "wake:moment": Record<string, never>;
  "agent:utterance": { id: string; speaker: string; text: string; tone: AgentTone };
  "agent:command": SceneEffect;
  "ui:intent": { source: string; text: string };
  /** 12 幕大秀进度：cmd 平台用；HUD 用它显示当前分镜 */
  "show:cue": { index: number; total: number; plan: ScenePlan };
  "show:state": { running: boolean; index: number };
};

export type EventName = keyof EventMap;
