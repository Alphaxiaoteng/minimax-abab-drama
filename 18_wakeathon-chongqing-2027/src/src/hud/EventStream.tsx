import { useEffect, useRef, useState } from "react";
import { bus, type AgentTone } from "../core/events";

interface Utterance {
  id: string;
  speaker: string;
  text: string;
  tone: AgentTone;
  ts: number;
}

const MAX_ITEMS = 60;

export function EventStream() {
  const [items, setItems] = useState<Utterance[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return bus.on("agent:utterance", (u) => {
      setItems((prev) => {
        const next = [...prev, { ...u, ts: Date.now() }];
        if (next.length > MAX_ITEMS) return next.slice(next.length - MAX_ITEMS);
        return next;
      });
    });
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [items]);

  return (
    <aside className="panel event-stream" aria-label="AI 事件流">
      <span className="panel-label">雾灵播报 · Agent Stream</span>
      <div className="stream-scroll" ref={scrollRef}>
        {items.length === 0 && <p className="stream-empty">等待第一条意图…</p>}
        {items.map((u) => (
          <article key={u.id} className={`stream-entry tone-${u.tone}`}>
            <time className="stream-ts">{new Date(u.ts).toLocaleTimeString("zh-CN", { hour12: false })}</time>
            <span className="stream-speaker">{u.speaker}</span>
            <p className="stream-text">{u.text}</p>
          </article>
        ))}
      </div>
    </aside>
  );
}