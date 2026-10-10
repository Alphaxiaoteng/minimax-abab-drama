// 可插拔 LLM 智能体：OpenAI 兼容 /chat/completions，失败静默降级到 FogSpriteAgent。
import type { ActionName, AgentTone, SceneEffect } from "../core/contract";
import type { AgentAdapter, AgentReply } from "./types";
import { INTENT_ACTIONS, makeEffect, parseIntent } from "./intents";
import { FogSpriteAgent } from "./mock-agent";

export interface LlmConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
}

const TONES: AgentTone[] = ["calm", "hype", "poetic", "warn"];
const TIMEOUT_MS = 8000;

const SYSTEM_PROMPT = [
  "你是「雾醒山城」2027 重庆跨年大秀的场景导演助手「雾灵」。",
  "根据用户意图编排视觉与音效命令，只输出一个 JSON 对象，禁止多余文字。",
  '严格 schema：{ "text": string, "tone": "calm"|"hype"|"poetic"|"warn", "commands": SceneEffect[], "sounds": SceneEffect[] }。',
  `SceneEffect 形如 { "action": string, "intensity": number }；action 只能是 ${INTENT_ACTIONS.join(", ")}；intensity 为 0..1。`,
  "台词要有重庆方言腔调与赛博感，tone 与台词情绪一致；无明确动作时回落到 skyline/fog。",
].join(" ");

// 归一化 action：词表校验 → 意图解析兜底 → 最终回落 skyline
function normalizeAction(value: unknown): ActionName {
  if (typeof value === "string") {
    const hit = INTENT_ACTIONS.find((a) => a === value.toLowerCase());
    if (hit) return hit;
    const p = parseIntent(value);
    if (p.matched.length > 0) return p.matched[0];
  }
  return "skyline";
}

// 数组项宽容解析：非法/缺失 intensity 按默认强度 0.6
function normalizeEffects(value: unknown): SceneEffect[] {
  if (!Array.isArray(value)) return [];
  const out: SceneEffect[] = [];
  for (const item of value) {
    if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      const intensity = typeof rec.intensity === "number" && Number.isFinite(rec.intensity) ? rec.intensity : 0.6;
      out.push(makeEffect(normalizeAction(rec.action), intensity));
    }
  }
  return out;
}

// 只截取首个 {…} 片段，容忍模型输出包裹代码围栏或多余解释
function parseResponse(content: string): AgentReply | null {
  const trimmed = content.trim();
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const data = JSON.parse(trimmed.slice(start, end + 1)) as Record<string, unknown>;
    if (typeof data.text !== "string" || data.text.length === 0) return null;
    const commands = normalizeEffects(data.commands);
    const sounds = normalizeEffects(data.sounds);
    if (commands.length === 0 && sounds.length === 0) return null;
    const tone = (TONES as readonly string[]).includes(String(data.tone)) ? (data.tone as AgentTone) : "calm";
    return { utterance: { text: data.text, tone }, commands, sounds };
  } catch {
    return null;
  }
}

// commands 全空时补一条 skyline+fog 兜底，保证视觉引擎有能量读数
function withFloor(reply: AgentReply): AgentReply {
  if (reply.commands.length > 0) return reply;
  const floor = parseIntent("");
  return { ...reply, commands: floor.commands, sounds: reply.sounds.length ? reply.sounds : floor.sounds };
}

export class LlmAgent implements AgentAdapter {
  readonly name = "雾灵 · LLM";
  private fallback = new FogSpriteAgent();

  constructor(private config: LlmConfig) {}

  async respond(intent: string): Promise<AgentReply> {
    try {
      const parsed = parseResponse(await this.chat(intent));
      if (parsed) return withFloor(parsed);
      throw new Error("llm 响应解析失败");
    } catch {
      return this.fallback.respond(intent);
    }
  }

  async onWakeMoment(): Promise<AgentReply> {
    try {
      const parsed = parseResponse(await this.chat("零点到了，唤醒整座山城！"));
      if (parsed) return withFloor(parsed);
      throw new Error("llm 响应解析失败");
    } catch {
      return this.fallback.onWakeMoment();
    }
  }

  // 8s 超时 + AbortController；非 2xx / 网络错误一律 reject（由调用方降级）
  private async chat(userText: string): Promise<string> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const url = `${this.config.baseUrl.replace(/\/+$/, "")}/chat/completions`;
      const res = await fetch(url, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({
          model: this.config.model,
          temperature: 0.7,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: SYSTEM_PROMPT },
            { role: "user", content: userText },
          ],
        }),
      });
      if (!res.ok) throw new Error(`http ${res.status}`);
      const json = (await res.json()) as { choices?: Array<{ message?: { content?: unknown } }> };
      const content = json.choices?.[0]?.message?.content;
      if (typeof content !== "string") throw new Error("missing content");
      return content;
    } finally {
      clearTimeout(timer);
    }
  }
}