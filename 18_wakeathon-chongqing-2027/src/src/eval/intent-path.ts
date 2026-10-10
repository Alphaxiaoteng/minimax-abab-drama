/**
 * 意图路径 —— 评测引擎跑 `intent` / `robust` 用例时，把注入的意图真正送进
 * AI 运行时（`AgentRuntime` + `FogSpriteAgent`），从而测的是
 * 「自然语言 → 命令」这条真实链路，而不是评测层自己伪造的效果。
 *
 * 评测期间 AgentRuntime 挂在 `show:PASSIVE` 模式（不订阅总线，避免与
 * 评测引擎自身的命令注入冲突），只暴露同步的 `send()` 转发。
 */
import { FogSpriteAgent } from "../ai/mock-agent";
import type { AgentReply } from "../core/contract";

export interface IntentPath {
  /** 注入一条意图（等价于 HUD 输入框提交），返回解析后的结构化回答 */
  send(text: string): Promise<AgentReply>;
}

/** 创建意图路径：直接复用演示路径的同一个智能体实现 */
export function createIntentPath(): IntentPath {
  const agent = new FogSpriteAgent();
  return { send: (text: string) => agent.respond(text) };
}
