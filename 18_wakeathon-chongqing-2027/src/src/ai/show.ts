// 大秀导演：按 12 幕分镜推进，用 setTimeout 队列驱动总线，stop() 保证清空所有定时器。
import type { SceneEffect, ScenePlan } from "../core/contract";
import { bus, nextId } from "../core/events";
import type { CueStep } from "../core/timeline";
import { SHOW_PLANS, buildTimeline } from "../core/timeline";

/** 每幕的发言角色（HUD 用它显示说话人；不用「（导演）」） */
const SPEAKERS: Record<string, string> = {
  lamplight: "两江灯火",
  riverfog: "江雾信使",
  lightcliff: "洪崖灯带",
  cruise: "朝天门船长",
  cableway: "长江索道",
  hotpot: "九宫格灶头",
  dronewa: "千机编队",
  countdown: "钟楼倒数",
  zero: "零点焰火",
  wake: "南山晨光",
  morning: "穿楼轻轨",
  fireworks_return: "雾醒山城",
};

const MIN_SPEED = 0.25;
const MAX_SPEED = 8;

export class ShowDirector {
  readonly plans: readonly ScenePlan[] = SHOW_PLANS;
  private steps: CueStep[] = buildTimeline(SHOW_PLANS);
  private timer: number | null = null;
  private currentIndex = -1;
  private isRunning = false;
  private speed = 1;
  // 待触发幕：记录未缩放剩余时长，setSpeed 时可按新倍速重挂
  private pendingIndex = -1;
  private pendingRemaining = 0;
  private pendingStart = 0;

  get running(): boolean {
    return this.isRunning;
  }

  get index(): number {
    return this.currentIndex;
  }

  start(): void {
    if (this.isRunning) return;
    this.isRunning = true;
    this.emitState();
    const from = this.currentIndex < 0 ? 0 : Math.min(this.currentIndex, this.steps.length - 1);
    this.fire(from);
  }

  stop(): void {
    this.clearTimer();
    this.pendingIndex = -1;
    this.isRunning = false;
    this.emitState();
  }

  /** 跳到某一幕：先清队列，再立刻下发该幕 cue */
  jumpTo(rawIndex: number): void {
    const index = Math.max(0, Math.min(Math.floor(rawIndex), this.steps.length - 1));
    this.clearTimer();
    this.pendingIndex = -1;
    this.fire(index);
  }

  /** 下一幕；已在最后一幕则收尾停演 */
  skip(): void {
    const next = this.currentIndex + 1;
    if (next >= this.steps.length) {
      this.stop();
      return;
    }
    this.jumpTo(next);
  }

  setSpeed(factor: number): void {
    if (!Number.isFinite(factor)) return;
    const next = Math.max(MIN_SPEED, Math.min(MAX_SPEED, factor));
    if (next === this.speed) return;
    this.speed = next;
    if (this.isRunning && this.timer !== null) {
      this.arm(this.pendingIndex, this.remaining());
    }
  }

  private fire(index: number): void {
    const step = this.steps[index];
    const plan = this.plans[step.planIndex];
    this.currentIndex = index;
    this.timer = null;
    this.pendingIndex = -1;

    bus.emit("show:cue", { index: step.planIndex, total: this.plans.length, plan });
    bus.emit("agent:utterance", {
      id: nextId(),
      speaker: SPEAKERS[plan.id] ?? plan.title,
      text: step.line,
      tone: step.tone,
    });
    this.apply(step.effect, step.accents);

    const nextStep = this.steps[index + 1];
    if (this.isRunning) {
      if (nextStep) this.arm(index + 1, nextStep.at - step.at);
      else this.stop();
    } else {
      this.emitState();
    }
  }

  private apply(effect: SceneEffect, accents: readonly SceneEffect[]): void {
    bus.emit("agent:command", effect);
    accents.forEach((accent) => bus.emit("agent:command", accent));
  }

  private arm(index: number, delayMs: number): void {
    this.clearTimer();
    this.pendingIndex = index;
    this.pendingRemaining = Math.max(0, delayMs);
    this.pendingStart = Date.now();
    this.timer = window.setTimeout(() => this.fire(index), this.pendingRemaining / this.speed);
    this.emitState();
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private remaining(): number {
    return Math.max(0, this.pendingRemaining - (Date.now() - this.pendingStart));
  }

  private emitState(): void {
    bus.emit("show:state", { running: this.isRunning, index: this.currentIndex });
  }
}