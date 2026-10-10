import type { EventName, EventMap } from "./contract";

export type { AgentTone, SceneEffect } from "./contract";

export type Handler<K extends EventName> = (payload: EventMap[K]) => void;

export class EventBus {
  private handlers = new Map<EventName, Set<(p: never) => void>>();

  on<K extends EventName>(name: K, fn: Handler<K>): () => void {
    let set = this.handlers.get(name);
    if (!set) {
      set = new Set();
      this.handlers.set(name, set);
    }
    set.add(fn as (p: never) => void);
    return () => this.off(name, fn);
  }

  off<K extends EventName>(name: K, fn: Handler<K>): void {
    this.handlers.get(name)?.delete(fn as (p: never) => void);
  }

  emit<K extends EventName>(name: K, payload: EventMap[K]): void {
    this.handlers.get(name)?.forEach((fn) => (fn as Handler<K>)(payload));
  }

  /** 订阅全部事件（调试台 / 评测记录器使用） */
  onAny(fn: (name: EventName, payload: unknown) => void): () => void {
    const offs: Array<() => void> = [];
    for (const name of this.names()) offs.push(this.on(name, (p) => fn(name, p)));
    return () => offs.forEach((off) => off());
  }

  names(): EventName[] {
    return ["countdown:tick", "wake:moment", "agent:utterance", "agent:command", "ui:intent", "show:cue", "show:state"];
  }
}

export const bus = new EventBus();

let seq = 0;
export const nextId = (): string => `evt-${Date.now().toString(36)}-${(seq++).toString(36)}`;

/**
 * 语速模型：中文按字数估算「口播」时长，用于分镜节拍与大秀总时长。
 * 命名保留为一个显式契约，12 幕排期与 HUD 节拍器共用同一口径。
 */
export function utteranceMs(text: string): number {
  return Math.min(9000, Math.max(2400, text.length * 190));
}
