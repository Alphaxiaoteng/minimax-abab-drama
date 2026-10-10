import { useEffect, useState } from "react";
import { bus } from "../core/events";

const NEW_YEAR_2027 = new Date("2027-01-01T00:00:00+08:00").getTime();
const YEAR_START = new Date("2026-01-01T00:00:00+08:00").getTime();
const YEAR_SPAN = NEW_YEAR_2027 - YEAR_START;

interface Remaining {
  d: number;
  h: number;
  m: number;
  s: number;
  done: boolean;
  progress: number;
}

function computeRemaining(): Remaining {
  const now = Date.now();
  const ms = NEW_YEAR_2027 - now;
  if (ms <= 0) return { d: 0, h: 0, m: 0, s: 0, done: true, progress: 1 };
  const s = Math.floor(ms / 1000);
  const progress = Math.min(1, Math.max(0, (now - YEAR_START) / YEAR_SPAN));
  return {
    d: Math.floor(s / 86400),
    h: Math.floor((s % 86400) / 3600),
    m: Math.floor((s % 3600) / 60),
    s: s % 60,
    done: false,
    progress,
  };
}

const pad = (n: number) => String(n).padStart(2, "0");

function FlipDigit({ value }: { value: string }) {
  const [prev, setPrev] = useState(value);
  const [flipping, setFlipping] = useState(false);

  useEffect(() => {
    if (value !== prev) {
      setFlipping(true);
      const t = setTimeout(() => {
        setPrev(value);
        setFlipping(false);
      }, 300);
      return () => clearTimeout(t);
    }
  }, [value, prev]);

  return (
    <span className={`flip-digit${flipping ? " flip" : ""}`}>
      <span className="flip-top">{prev}</span>
      <span className="flip-bottom">{value}</span>
    </span>
  );
}

export function Countdown() {
  const [r, setR] = useState(computeRemaining);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = computeRemaining();
      setR(next);
      bus.emit("countdown:tick", { remainingMs: NEW_YEAR_2027 - Date.now() });
      if (next.done) bus.emit("wake:moment", {});
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const circumference = 2 * Math.PI * 42;
  const dashOffset = circumference * (1 - r.progress);

  return (
    <section className="panel countdown" aria-label="跨年倒计时">
      <span className="panel-label">距离 2027 · 重庆零点</span>
      <div className="countdown-row">
        <div className="progress-ring" aria-hidden>
          <svg viewBox="0 0 100 100">
            <circle className="ring-bg" cx="50" cy="50" r="42" />
            <circle
              className="ring-fg"
              cx="50"
              cy="50"
              r="42"
              strokeDasharray={`${circumference}`}
              strokeDashoffset={dashOffset}
            />
          </svg>
          <span className="ring-pct tabular">{Math.round(r.progress * 100)}%</span>
        </div>
        {r.done ? (
          <strong className="wake-text">新年已醒来</strong>
        ) : (
          <div className="clock">
            <div className="clock-unit">
              <FlipDigit value={String(r.d)} />
              <i>天</i>
            </div>
            <div className="clock-unit">
              <FlipDigit value={pad(r.h)} />
              <i>时</i>
            </div>
            <div className="clock-unit">
              <FlipDigit value={pad(r.m)} />
              <i>分</i>
            </div>
            <div className="clock-unit">
              <FlipDigit value={pad(r.s)} />
              <i>秒</i>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}