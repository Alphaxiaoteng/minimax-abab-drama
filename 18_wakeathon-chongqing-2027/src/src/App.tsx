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
import { CameraDirectorDock } from "./hud/CameraDirectorDock";
import { WeatherControlDock, type WeatherControlProps } from "./hud/WeatherControlDock";
import { TrafficInfoPanel, type TrafficAgentInfo } from "./hud/TrafficInfoPanel";
import { getCameraDirector } from "./camera/director";

declare global {
  interface Window {
    __wakeShow?: {
      setEngine(kind: EngineKind): void;
      apply(effect: SceneEffect): void;
      sample(): Record<string, number>;
      getCameraDirector(): any;
      getCurrentWeatherControls(): WeatherControlProps | null;
    };
  }
}

const CAMERA_TRANSFORMS: Record<string, string> = {
  wide: "scale(0.82)",
  river: "perspective(1000px) rotateX(7deg) scale(1.1)",
  lowAngle: "perspective(1000px) rotateX(-11deg) scale(1.14)",
  overlook: "perspective(1100px) rotateX(20deg) scale(1.06)",
  jfb: "perspective(1100px) rotateX(20deg) scale(1.06)",
  hyd: "perspective(1000px) rotateX(-5deg) scale(1.15)",
  nanshan: "scale(0.78)",
  suodao: "perspective(800px) rotateX(3deg) scale(1.08)",
  rail: "perspective(900px) rotateX(-2deg) scale(1.12)",
};

type LiveEngine = SceneRenderer & { start(): void; sampleState(): Record<string, number> };

export default function App() {
  const mountRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<LiveEngine | null>(null);
  const cameraDirectorRef = useRef<any>(null);
  const fpsRef = useRef(0);

  const [engine, setEngine] = useState<EngineKind>("three");
  const [fps, setFps] = useState(0);
  const [lines, setLines] = useState<string[]>([]);
  const [weatherControls, setWeatherControls] = useState<WeatherControlProps>({
    fogDensity: 0.5,
    volumetricLight: 0.7,
    bloomIntensity: 0.9,
  });
  const [trafficAgentInfo, setTrafficAgentInfo] = useState<TrafficAgentInfo | null>(null);

  const pushLine = useCallback((line: string) => {
    const stamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLines((prev) => [...prev.slice(-39), `${stamp}  ${line}`]);
  }, []);

  useEffect(() => {
    cameraDirectorRef.current = getCameraDirector();
    return () => {};
  }, []);

  useEffect(() => {
    const runtime = new AgentRuntime(new FogSpriteAgent());
    runtime.start();
    return () => runtime.stop();
  }, []);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: SkyEngine | CssRenderer;
    try {
      renderer = engine === "three" ? new SkyEngine(mount) : new CssRenderer(mount);
    } catch (err) {
      if (engine === "three") {
        pushLine("Three.js init failed, downgraded to CSS");
        setEngine("css");
        return;
      }
      pushLine(`CSS init failed: ${String(err)}`);
      return;
    }

    renderer.start();
    rendererRef.current = renderer;
    pushLine(`Engine: ${engine === "three" ? "Three.js" : "CSS"}`);

    return () => {
      (renderer as SceneRenderer).dispose();
      rendererRef.current = null;
      mount.style.transform = "none";
    };
  }, [engine, pushLine]);

  useEffect(() => {
    let frames = 0;
    let last = performance.now();
    let raf = 0;
    const tick = () => {
      frames += 1;
      const now = performance.now();
      if (now - last >= 500) {
        fpsRef.current = (frames * 1000) / (now - last);
        setFps(Math.round(fpsRef.current));
        frames = 0;
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const offIntent = bus.on("ui:intent", ({ text }) => {
      const cam = Object.keys(CAMERA_TRANSFORMS).find((w) => text.includes(w));
      if (cam && mountRef.current) {
        mountRef.current.style.transform = CAMERA_TRANSFORMS[cam];
        pushLine(`Camera: ${cam}`);
      }
    });
    const offCommand = bus.on("agent:command", (effect) => {
      pushLine(`${effect.action}: ${effect.intensity.toFixed(2)}`);
    });
    const offCue = bus.on("show:cue", ({ index, total }) => {
      pushLine(`Scene: ${index + 1}/${total}`);
    });
    const offWake = bus.on("wake:moment", () => pushLine("Wake!"));
    
    const offFog = bus.on("weather:fogDensity", ({ value }) => 
      setWeatherControls(p => ({ ...p, fogDensity: value }))
    );
    const offLight = bus.on("weather:volumetricLight", ({ value }) => 
      setWeatherControls(p => ({ ...p, volumetricLight: value }))
    );
    const offBloom = bus.on("weather:bloom", ({ value }) => 
      setWeatherControls(p => ({ ...p, bloomIntensity: value }))
    );
    const offFireworks = bus.on("weather:fireworks", () => pushLine("FW triggered"));
    const offTrafficClick = bus.on("traffic:agentClick", (info: TrafficAgentInfo) => 
      setTrafficAgentInfo(info)
    );

    return () => {
      offIntent(); offCommand(); offCue(); offWake();
      offFog(); offLight(); offBloom(); offFireworks(); offTrafficClick();
    };
  }, [pushLine]);

  useEffect(() => {
    window.__wakeShow = {
      setEngine: (kind) => setEngine(kind),
      apply: (effect) => bus.emit("agent:command", effect),
      sample: () => rendererRef.current?.sampleState() ?? {},
      getCameraDirector: () => cameraDirectorRef.current,
      getCurrentWeatherControls: () => ({ ...weatherControls }),
    };
    return () => {
      delete window.__wakeShow;
    };
  }, [weatherControls]);

  return (
    <div className="stage">
      <div ref={mountRef} className="canvas-mount" />
      <div className="hud-fx" aria-hidden />
      <header className="brand">
        <h1>雾醒山城</h1>
        <p>WAKE UP WITH AI · 2027 Chongqing</p>
      </header>
      <div className="hud">
        <div className="hud-col">
          <Countdown />
          <CueRail />
        </div>
        <EventStream />
        <div className="dock-top-panel">
          <CameraDirectorDock />
          <WeatherControlDock controls={weatherControls} />
        </div>
        <ControlDock engine={engine} onEngineChange={setEngine} />
      </div>
      {trafficAgentInfo && (
        <TrafficInfoPanel agentInfo={trafficAgentInfo} onClose={() => setTrafficAgentInfo(null)} />
      )}
      <DebugPanel lines={lines} fps={fps} />
    </div>
  );
}
