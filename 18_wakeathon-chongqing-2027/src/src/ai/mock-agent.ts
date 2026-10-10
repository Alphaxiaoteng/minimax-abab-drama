// 关键词/规则型智能体：走 intents 解析，保证纯确定性、可评测。
import type { AgentAdapter, AgentReply } from "./types";
import { parseIntent } from "./intents";

export class FogSpriteAgent implements AgentAdapter {
  readonly name = "雾灵 · FogSprite";

  async respond(intent: string): Promise<AgentReply> {
    const p = parseIntent(intent);
    return {
      utterance: { text: p.text, tone: p.tone },
      commands: p.commands,
      sounds: p.sounds,
    };
  }

  async onWakeMoment(): Promise<AgentReply> {
    return {
      utterance: {
        text: "WAKE UP WITH AI——2027，重庆醒了我也叫醒了。新一年每一次出发，都从这座不夜城起跳。",
        tone: "hype",
      },
      commands: [
        { action: "fireworks", intensity: 1 },
        { action: "dawn", intensity: 1 },
        { action: "skyline", intensity: 1 },
      ],
      sounds: [
        { action: "shatter", intensity: 1 },
        { action: "laser", intensity: 1 },
      ],
    };
  }
}