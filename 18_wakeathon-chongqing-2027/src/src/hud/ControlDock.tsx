import { useEffect, useRef, useState } from "react";
import { bus } from "../core/events";
import type { EngineKind } from "../core/contract";
import { EngineToggle } from "./EngineToggle";

const QUICK_INTENTS = [
  "江雾再浓一点",
  "给天际线打一束霓虹",
  "来一发洪崖洞烟花",
  "把 2027 的黎明叫醒",
];

const CAMERA_PRESETS = ["远景", "江面", "仰视", "俯瞰"];

interface Props {
  engine: EngineKind;
  onEngineChange(next: EngineKind): void;
}

export function ControlDock({ engine, onEngineChange }: Props) {
  const [text, setText] = useState("");
  const [demoSeconds, setDemoSeconds] = useState<number | null>(null);
  const [speed, setSpeed] = useState<"0.5x" | "1x" | "2x">("1x");
  const demoTimer = useRef<number | null>(null);

  useEffect(() => {
    if (demoSeconds === null) return;
    if (demoSeconds <= 0) {
      bus.emit("wake:moment", {});
      setDemoSeconds(null);
      return;
    }
    demoTimer.current = window.setTimeout(
      () => setDemoSeconds((s) => (s ?? 1) - 1),
      1000,
    );
    return () => {
      if (demoTimer.current !== null) window.clearTimeout(demoTimer.current);
    };
  }, [demoSeconds]);

  const send = (value: string) => {
    const intent = value.trim();
    if (!intent) return;
    bus.emit("ui:intent", { source: "hud", text: intent });
    setText("");
  };

  const emitSpeed = () => {
    bus.emit("ui:intent", { source: "hud", text: `倍速${speed}` });
  };

  return (
    <section className="panel dock" aria-label="交互控制台">
      <div className="dock-top">
        <span className="panel-label">指挥中心 · Command Dock</span>
        <EngineToggle engine={engine} onChange={onEngineChange} />
      </div>

      <form
        className="dock-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="例：让嘉陵江的雾漫过解放碑"
          aria-label="意图输入"
        />
        <button type="submit">唤醒</button>
      </form>

      <div className="dock-row">
        <div className="chips">
          {QUICK_INTENTS.map((q) => (
            <button key={q} type="button" className="chip" onClick={() => send(q)}>
              {q}
            </button>
          ))}
          <button
            type="button"
            className="chip wake"
            onClick={() => bus.emit("wake:moment", {})}
          >
            触发唤醒时刻
          </button>
          <button
            type="button"
            className="chip demo"
            onClick={() => setDemoSeconds(10)}
            disabled={demoSeconds !== null}
          >
            {demoSeconds === null ? "10 秒倒计时演示" : `${demoSeconds} 秒后零点`}
          </button>
        </div>
      </div>

      <div className="dock-row dock-controls">
        <div className="dock-group">
          <span className="dock-group-label">大秀控制</span>
          <div className="chips">
            <button
              type="button"
              className="chip"
              onClick={() => bus.emit("ui:intent", { source: "hud", text: "开始大秀" })}
            >
              开始
            </button>
            <button
              type="button"
              className="chip"
              onClick={() =>
                bus.emit("ui:intent", { source: "hud", text: "跳转到第3幕" })
              }
            >
              跳转幕
            </button>
            {(["0.5x", "1x", "2x"] as const).map((s) => (
              <button
                key={s}
                type="button"
                className={`chip${speed === s ? " active" : ""}`}
                onClick={() => {
                  setSpeed(s);
                  bus.emit("ui:intent", { source: "hud", text: `倍速${s}` });
                }}
              >
                {s}
              </button>
            ))}
            <button type="button" className="chip" onClick={emitSpeed}>
              应用
            </button>
          </div>
        </div>

        <div className="dock-group">
          <span className="dock-group-label">镜头预设</span>
          <div className="chips">
            {CAMERA_PRESETS.map((cam) => (
              <button
                key={cam}
                type="button"
                className="chip"
                onClick={() =>
                  bus.emit("ui:intent", { source: "hud", text: cam })
                }
              >
                {cam}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}