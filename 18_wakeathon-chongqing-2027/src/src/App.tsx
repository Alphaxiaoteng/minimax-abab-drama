import { useCallback, useEffect, useRef, useState } from "react";
import type { EngineKind, SceneEffect, SceneRenderer } from "./core/contract";
import { bus } from "./core/events";
import { SkyEngine } from "./visual/sky-engine";
import { CssRenderer } from "./css/renderer";
import { AgentRuntime } from "./ai/runtime";
import { FogSpriteAgent } from "./ai/mock-agent";
import { Countdown } from "./hud/Countdown";
import { EventStream } from "./hud/EventStream";
import { CueRail } from "./hud/CueRail";
import { ControlDock } from "./hud/ControlDock";
import { DebugPanel } from "./hud/DebugPanel";

declare global {
  interface Window {
    __wakeShow?: {
      setEngine(kind: EngineKind): void;
      apply(effect: SceneEffect): void;
      sample(): Record<string, number>;
    };
  }
}

// 相机预设：SkyEngine / CssRenderer 均未暴露 camera API（契约只含 apply/reset/dispose/start），
// 因此在 App 层对渲染容器做 CSS transform 兜底。若引擎后续提供镜头方法，替换本表的落地方式即可。
const CAMERA_TRANSFORMS: Record<string, string> = {
  远景: "scale(0.82)",
  江面: "perspective(1000px) rotateX(7deg) scale(1.1)",
  仰视: "perspective(1000px) rotateX(-11deg) scale(1.14)",
  俯瞰: "perspective(1100px) rotateX(20deg) scale(1.06)",
};

const CAMERA_WORDS = Object.keys(CAMERA_TRANSFORMS);

/** 引擎实例的可扩展面：契约只约定 apply/reset/dispose，start 与 sampleState 由两阵营共同实现 */
type LiveEngine = SceneRenderer & { start(): void; sampleState(): Record<string, number> };

export default function App() {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<LiveEngine | null>(null);
  const fpsRef = useRef(0);

  const [engine, setEngine] = useState<EngineKind>("three");
  const [fps, setFps] = useState(0);
  const [lines, setLines] = useState<string[]>([]);

  const pushLine = useCallback((line: string) => {
    const stamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLines((prev) => [...prev.slice(-39), `${stamp}  ${line}`]);
  }, []);

  // 大秀 runtime（意图 → 台词 + 场景命令），与引擎生命周期解耦，仅挂载一次。
  useEffect(() => {
    const runtime = new AgentRuntime(new FogSpriteAgent());
    runtime.start();
    return () => runtime.stop();
  }, []);

  // 引擎生命周期：engine 变化时创建/销毁对应阵营，three 初始化异常自动降级 css。
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: SkyEngine | CssRenderer;
    try {
      renderer = engine === "three" ? new SkyEngine(mount) : new CssRenderer(mount);
    } catch (err) {
      if (engine === "three") {
        pushLine("three 引擎初始化失败，已降级至 CSS");
        setEngine("css");
        return;
      }
      pushLine(`CSS 引擎初始化失败：${String(err)}`);
      return;
    }

    renderer.start();
    rendererRef.current = renderer;
    pushLine(`渲染引擎：${engine === "three" ? "Three.js" : "CSS"}`);

    return () => {
      (renderer as SceneRenderer).dispose();
      rendererRef.current = null;
      mount.style.transform = "none";
    };
  }, [engine, pushLine]);

  // FPS 采样循环。
  useEffect(() => {
    let frames = 0;
    let last = performance.now();
    let raf = 0;
    const tick = () => {
      frames += 1;
      const now = performance.now();
      if (now - last >= 500) {
        const value = (frames * 1000) / (now - last);
        fpsRef.current = value;
        setFps(Math.round(value));
        frames = 0;
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // ui:intent 监听：命中镜头词切换相机预设；其余事件写调试日志。
  useEffect(() => {
    const offIntent = bus.on("ui:intent", ({ text }) => {
      const cam = CAMERA_WORDS.find((w) => text.includes(w));
      if (cam && mountRef.current) {
        mountRef.current.style.transform = CAMERA_TRANSFORMS[cam];
        pushLine(`镜头预设：${cam}`);
      }
    });
    const offCommand = bus.on("agent:command", (effect) => {
      pushLine(`场景命令：${effect.action} ×${effect.intensity.toFixed(2)}`);
    });
    const offCue = bus.on("show:cue", ({ index, total }) => {
      pushLine(`分镜推进：${index + 1}/${total}`);
    });
    const offWake = bus.on("wake:moment", () => pushLine("唤醒时刻触发"));
    return () => {
      offIntent();
      offCommand();
      offCue();
      offWake();
    };
  }, [pushLine]);

  // 评测/自动化接口。
  useEffect(() => {
    window.__wakeShow = {
      setEngine: (kind) => setEngine(kind),
      apply: (effect) => bus.emit("agent:command", effect),
      sample: () => rendererRef.current?.sampleState() ?? {},
    };
    return () => {
      delete window.__wakeShow;
    };
  }, []);

  return (
    <div className="stage">
      <div ref={mountRef} className="canvas-mount" />
      <div className="hud-fx" aria-hidden />
      <header className="brand">
        <h1>雾醒山城</h1>
        <p>WAKE UP WITH AI · 2027 重庆跨年 AI 原型</p>
      </header>
      <div className="hud">
        <div className="hud-col">
          <Countdown />
          <CueRail />
        </div>
        <EventStream />
        <ControlDock engine={engine} onEngineChange={setEngine} />
      </div>
      <DebugPanel lines={lines} fps={fps} />
    </div>
  );
}