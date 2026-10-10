// 运行时总线接线：ui:intent 命中「大秀」类词交导演，其余交适配器；wake:moment 走彩蛋。
import { bus, nextId } from "../core/events";
import type { AgentAdapter, AgentReply } from "./types";
import { ShowDirector } from "./show";

// 触发自动大秀的意图词
const SHOW_WORDS = ["大秀", "开场", "全程", "自动演出", "整场", "演一场", "开始演出", "full show", "run the show"];

export class AgentRuntime {
  private unsubscribe: Array<() => void> = [];
  private readonly ownsDirector: boolean;
  readonly director: ShowDirector;

  constructor(private adapter: AgentAdapter, director?: ShowDirector) {
    this.ownsDirector = director === undefined;
    this.director = director ?? new ShowDirector();
  }

  start(): void {
    this.unsubscribe.push(
      bus.on("ui:intent", ({ text, source }) => {
        void this.handle(text, source);
      }),
      bus.on("wake:moment", () => {
        void this.speak(this.adapter.onWakeMoment());
      }),
    );
  }

  /** 直接送达一条意图（HUD 之外的程序化入口：评测、自动化演示、外接控制器） */
  send(text: string, source = "program"): void {
    void this.handle(text, source);
  }

  stop(): void {
    this.unsubscribe.forEach((off) => off());
    this.unsubscribe = [];
    if (this.ownsDirector) this.director.stop();
  }

  private async handle(text: string, source: string): Promise<void> {
    const lowered = text.toLowerCase();
    if (SHOW_WORDS.some((w) => lowered.includes(w))) {
      this.director.start();
      return;
    }
    this.speak(this.adapter.respond(`${source}: ${text}`));
  }

  // 台词进事件流供 HUD，命令与音效副能量都下发到视觉引擎
  private async speak(promise: Promise<AgentReply>): Promise<void> {
    const reply = await promise;
    bus.emit("agent:utterance", {
      id: nextId(),
      speaker: this.adapter.name,
      text: reply.utterance.text,
      tone: reply.utterance.tone,
    });
    [...reply.commands, ...reply.sounds].forEach((command) => bus.emit("agent:command", command));
  }
}