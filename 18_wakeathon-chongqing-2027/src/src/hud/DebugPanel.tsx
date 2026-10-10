import { useEffect, useRef, useState } from "react";

interface Props {
  lines: string[];
  fps: number;
}

/** 可折叠调试面板：FPS + 事件日志，默认折叠 */
export function DebugPanel({ lines, fps }: Props) {
  const [open, setOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines, open]);

  return (
    <section className={`panel debug-panel${open ? " open" : ""}`} aria-label="调试面板">
      <button
        type="button"
        className="debug-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="debug-fps tabular">{fps.toFixed(0)} FPS</span>
        <span className="debug-chevron">{open ? "▼" : "▲"}</span>
      </button>
      {open && (
        <div className="debug-log" ref={logRef}>
          {lines.map((line, i) => (
            <div key={i} className="debug-line">
              {line}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
