import { useEffect, useState } from "react";
import { bus } from "../core/events";
import { SHOW_PLANS } from "../core/timeline";

interface State {
  running: boolean;
  index: number;
}

export function CueRail() {
  const [current, setCurrent] = useState<State>({ running: false, index: -1 });

  useEffect(() => {
    const offCue = bus.on("show:cue", ({ index }) => {
      setCurrent((prev) => ({ ...prev, index }));
    });
    const offState = bus.on("show:state", ({ running, index }) => {
      setCurrent({ running, index });
    });
    return () => {
      offCue();
      offState();
    };
  }, []);

  return (
    <section className="panel cue-rail" aria-label="分镜轨道">
      <span className="panel-label">分镜轨道 · Cue Rail</span>
      <div className="rail-track">
        {SHOW_PLANS.map((plan, i) => (
          <button
            key={plan.id}
            type="button"
            className={`rail-cell${i === current.index ? " active" : ""}${current.running ? " running" : ""}`}
            onClick={() => bus.emit("ui:intent", { source: "cue", text: `跳转到第${i + 1}幕` })}
            title={`${i + 1}. ${plan.title}`}
            aria-label={`第${i + 1}幕 ${plan.title}`}
          >
            <span className="rail-num">{i + 1}</span>
            <span className="rail-title">{plan.title}</span>
          </button>
        ))}
      </div>
    </section>
  );
}