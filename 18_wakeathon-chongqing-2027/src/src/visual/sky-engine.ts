import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { bus } from "../core/events";
import type { ActionName, SceneEffect, SceneRenderer } from "../core/contract";
import { NEON, NIGHT_BG, DAWN_BG, NIGHT_FOG, DAWN_FOG, NIGHT_SUN, DAWN_SUN } from "./palette";
import { Rng } from "./rng";
import { disposeTextures } from "./texture";
import { City } from "./city";
import { FogField } from "./fog";
import { FireworksShow } from "./fireworks";
import { LaserFan } from "./lasers";
import { DroneSquadron } from "./drones";
import { HotpotMascot } from "./mascot";
import { SpotlightRig } from "./spotlights";
import { ConfettiRain } from "./confetti";
import { createGlitchPass } from "./glitch";

const ACTIONS: readonly ActionName[] = [
  "fog", "skyline", "dawn", "fireworks", "laser", "drone",
  "mascot", "spotlight", "confetti", "glitch", "shatter",
];

const WHITE = new THREE.Color(0xffffff);
const BASE_BLOOM = 0.95;
const DECAY = 0.6; // 能量时间常数 ~1.6s

export interface SkyEngineOptions {
  tier?: "high" | "low";
}

/** 动作能量（0..1），时间只来自 advance(dt) */
type Energy = Record<ActionName, number>;

/**
 * WebGL 主引擎：12 幕大秀的场景渲染阵营实现。
 * - 视觉时间线完全由外部 advance(dt) 驱动，同 dt 序列 ⇒ 同 sample 读数。
 * - apply() 对能量做「尖峰 + 指数衰减」，dawn 为单调累积。
 */
export class SkyEngine implements SceneRenderer {
  readonly kind = "three" as const;

  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private composer: EffectComposer;
  private bloomPass: UnrealBloomPass;
  private glitch: { pass: ShaderPass; setStrength: (s: number) => void; setTime: (t: number) => void };
  private clock = new THREE.Clock();

  private city: City;
  private fogField: FogField;
  private fireworks: FireworksShow;
  private lasers: LaserFan;
  private drones: DroneSquadron;
  private mascot: HotpotMascot;
  private spotlights: SpotlightRig;
  private confetti: ConfettiRain;

  private sceneFog = new THREE.FogExp2(NIGHT_FOG.getHex(), 0.012);
  private sun: THREE.DirectionalLight;
  private hemi: THREE.HemisphereLight;

  private energy: Energy = {
    fog: 0, skyline: 0, dawn: 0, fireworks: 0, laser: 0, drone: 0,
    mascot: 0, spotlight: 0, confetti: 0, glitch: 0, shatter: 0,
  };
  private dawnLevel = 0;
  private dawnTarget = 0;
  private shatterLevel = 0;

  private elapsed = 0;
  private raf = 0;
  private running = false;
  private pointer = new THREE.Vector2(0, 0);
  private disposers: Array<() => void> = [];
  private bg = new THREE.Color();

  constructor(private mount: HTMLElement, opts: SkyEngineOptions = {}) {
    const low = opts.tier === "low";
    // 固定种子：同 apply 序列 + 同 dt 序列 ⇒ 同视觉/同读数（含粒子散布）
    const rng = new Rng(0x5eeca11e);
    this.city = new City(rng);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: !low, alpha: false, powerPreference: "high-performance" });
    } catch (e) {
      throw new Error("WebGL unavailable: " + (e instanceof Error ? e.message : String(e)));
    }
    if (!renderer.getContext()) {
      throw new Error("WebGL unavailable: null context");
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, low ? 1 : 2));
    renderer.setSize(this.clientWidth(), this.clientHeight());
    renderer.shadowMap.enabled = !low;
    this.renderer = renderer;
    this.mount.appendChild(renderer.domElement);

    this.scene.background = this.bg.copy(NIGHT_BG);
    this.scene.fog = this.sceneFog;

    this.camera = new THREE.PerspectiveCamera(58, this.clientWidth() / this.clientHeight(), 0.1, 320);
    this.camera.position.set(0, 13, 58);
    this.camera.lookAt(0, 9, -20);

    this.hemi = new THREE.HemisphereLight(0x33406b, 0x0a0d18, 0.5);
    this.sun = new THREE.DirectionalLight(NIGHT_SUN.getHex(), 0.4);
    this.sun.position.set(-30, 40, 10);
    const neonKey = new THREE.PointLight(NEON[1], low ? 70 : 120, 130, 2);
    neonKey.position.set(20, 12, -8);
    const cyanKey = new THREE.PointLight(NEON[0], low ? 70 : 110, 140, 2);
    cyanKey.position.set(-25, 16, -30);
    const potKey = new THREE.PointLight(NEON[2], low ? 50 : 90, 60, 2);
    potKey.position.set(14, 3, 24);

    const fogCount = low ? 400 : 560;
    const fwCap = low ? 2100 : 4200;
    const droneCap = low ? 128 : 220;
    const bubbleCount = low ? 90 : 180;
    const steamCount = low ? 60 : 120;
    const confettiCap = low ? 600 : 1200;
    const laserCount = low ? 5 : 9;

    this.fogField = new FogField(fogCount, rng);
    this.fireworks = new FireworksShow(fwCap, rng);
    this.lasers = new LaserFan(laserCount);
    this.drones = new DroneSquadron(droneCap, rng);
    this.mascot = new HotpotMascot(bubbleCount, steamCount, rng);
    this.spotlights = new SpotlightRig();
    this.confetti = new ConfettiRain(confettiCap, rng);

    this.scene.add(
      this.city.group,
      this.fogField.points,
      this.fireworks.points,
      this.lasers.group,
      this.drones.points,
      this.mascot.group,
      this.spotlights.group,
      this.confetti.mesh,
      this.hemi,
      this.sun,
      neonKey,
      cyanKey,
      potKey,
    );

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloomPass = new UnrealBloomPass(
      new THREE.Vector2(this.clientWidth(), this.clientHeight()),
      BASE_BLOOM, low ? 0.4 : 0.55, low ? 0.4 : 0.55,
    );
    this.composer.addPass(this.bloomPass);
    this.glitch = createGlitchPass();
    this.composer.addPass(this.glitch.pass);
    this.composer.addPass(new OutputPass());
    this.composer.setSize(this.clientWidth(), this.clientHeight());

    const onResize = () => {
      const w = this.clientWidth();
      const h = this.clientHeight();
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h);
      this.composer.setSize(w, h);
      this.bloomPass.setSize(w, h);
    };
    const onPointer = (e: PointerEvent) => {
      this.pointer.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1);
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointer);
    this.disposers.push(
      () => window.removeEventListener("resize", onResize),
      () => window.removeEventListener("pointermove", onPointer),
      bus.on("agent:command", (cmd) => this.apply(cmd)),
      bus.on("wake:moment", () => {
        this.dawnTarget = 1;
        this.energy.dawn = Math.max(this.energy.dawn, 1);
        this.fireworks.volley(1, 5);
        this.energy.fireworks = 1;
        this.energy.shatter = Math.max(this.energy.shatter, 0.7);
        this.shatterLevel = Math.max(this.shatterLevel, 0.7);
      }),
    );
  }

  private clientWidth(): number {
    return Math.max(1, this.mount.clientWidth);
  }
  private clientHeight(): number {
    return Math.max(1, this.mount.clientHeight);
  }

  apply(effect: SceneEffect): void {
    const v = Math.max(0, Math.min(1, effect.intensity));
    if (effect.action === "dawn") {
      this.dawnTarget = Math.min(1, this.dawnTarget + v);
      return;
    }
    if (effect.action === "fireworks") {
      this.fireworks.volley(v, Math.max(1, Math.round(2 + v * 4)));
    }
    this.energy[effect.action] = Math.max(this.energy[effect.action], v);
    if (effect.action === "shatter") {
      this.shatterLevel = Math.max(this.shatterLevel, v);
    }
  }

  /** 推进一帧（唯一时间来源）。App 用 RAF 的真实 dt，评测用固定 dt。 */
  advance(dt: number): void {
    if (!(dt > 0)) return;
    const clamped = Math.min(0.05, dt);
    this.elapsed += clamped;

    this.dawnLevel += (this.dawnTarget - this.dawnLevel) * Math.min(1, clamped * 0.6);
    for (const action of ACTIONS) {
      if (action === "dawn") continue;
      this.energy[action] *= Math.exp(-DECAY * clamped);
    }
    this.energy.dawn = this.dawnLevel;
    this.shatterLevel *= Math.exp(-clamped * 2.5);

    const e = this.energy;
    const t = this.elapsed;
    this.applyDawnPalette();

    this.city.setPulse(e.skyline);
    this.city.update(t);
    this.fogField.update(clamped, e.fog);
    this.fireworks.update(clamped);
    this.lasers.update(t, e.laser);
    this.drones.update(t, e.drone);
    this.mascot.update(t, clamped, e.mascot);
    this.spotlights.update(t, e.spotlight);
    this.confetti.update(clamped, e.confetti);

    this.bloomPass.strength = BASE_BLOOM + this.shatterLevel * 1.9;
    this.glitch.setStrength(e.glitch);
    this.glitch.setTime(t);

    this.updateCamera(t);
    this.composer.render();
  }

  /** 当前能量读数（0..1，纯状态，不读任何时钟） */
  sample(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const action of ACTIONS) out[action] = Math.max(0, Math.min(1, this.energy[action]));
    return out;
  }

  /** 与 CSS 阵营同名的读数入口：App 的 window.__wakeShow.sample() 两阵营通用 */
  sampleState(): Record<string, number> {
    return this.sample();
  }

  private applyDawnPalette(): void {
    const d = this.dawnLevel;
    const flash = this.shatterLevel;
    this.bg.copy(NIGHT_BG).lerp(DAWN_BG, d).lerp(WHITE, flash * 0.85);
    (this.scene.background as THREE.Color).copy(this.bg);
    this.sceneFog.color.copy(NIGHT_FOG).lerp(DAWN_FOG, d);
    this.sceneFog.density = 0.012 - d * 0.006;
    this.hemi.intensity = 0.5 + d * 0.9 + flash * 0.4;
    this.sun.intensity = 0.4 + d * 1.6;
    this.sun.color.copy(NIGHT_SUN).lerp(DAWN_SUN, d);
    // 太阳角度随黎明上升并转向江面
    this.sun.position.set(-30 + d * 30, 40 - d * 28, 10 + d * 55);
  }

  private updateCamera(t: number): void {
    const sway = Math.sin(t * 0.05) * 3;
    const shake = this.shatterLevel;
    this.camera.position.set(
      sway + this.pointer.x * 4 + Math.sin(t * 57) * shake * 0.5,
      13 - this.pointer.y * 2 + Math.cos(t * 71) * shake * 0.5,
      58 + Math.sin(t * 49) * shake * 0.5,
    );
    this.camera.lookAt(0, 9, -20);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    const tick = () => {
      if (!this.running) return;
      this.raf = requestAnimationFrame(tick);
      const dt = Math.min(0.05, this.clock.getDelta());
      this.advance(dt);
    };
    tick();
  }

  reset(): void {
    for (const action of ACTIONS) this.energy[action] = 0;
    this.dawnLevel = 0;
    this.dawnTarget = 0;
    this.shatterLevel = 0;
    this.elapsed = 0;
    this.bloomPass.strength = BASE_BLOOM;
    this.glitch.setStrength(0);
    this.city.setPulse(0);
    this.fogField.reset();
    this.fireworks.reset();
    this.lasers.reset();
    this.drones.reset();
    this.mascot.reset();
    this.spotlights.reset();
    this.confetti.reset();
  }

  dispose(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.disposers.forEach((fn) => fn());
    this.disposers = [];
    this.city.dispose();
    this.fogField.dispose();
    this.fireworks.dispose();
    this.lasers.dispose();
    this.drones.dispose();
    this.mascot.dispose();
    this.spotlights.dispose();
    this.confetti.dispose();
    this.glitch.pass.dispose();
    this.bloomPass.dispose();
    this.composer.dispose();
    this.renderer.dispose();
    disposeTextures();
    this.renderer.domElement.remove();
  }
}

// 手工验证步骤：
// 1) `npm run dev`（默认 http://localhost:5173）
// 2) 底部控制台点「江雾再浓一点」→ fog 粒子增浓；点「给天际线打一束霓虹」→ skyline 灯带脉冲；
//    点「来一发洪崖洞烟花」→ 烟花牡丹/双环/柳条空爆；点「把 2027 的黎明叫醒」→ dawn 色温迁移。
// 3) 点「直接触发唤醒时刻」→ wake:moment：黎明 + 多弹烟花 + 白闪/震动（shatter）。
// 4) laser/drone/mascot/spotlight/confetti/glitch/shatter 走分幕剧本：可在浏览器控制台执行
//    bus.emit("agent:command", { action:"drone", intensity:1 }) 等逐条验证（action 取 11 个之一）。
// 5) 评测定性：URL 加 ?eval=1 后 window.__wakeEval.runAll({dt:16, only:null})。
// 6) 降级：new SkyEngine(mount, { tier:"low" }) 粒子减半、关阴影、pixelRatio 上限 1。
// 7) WebGL 不可用：捕获 SkyEngine 构造函数抛出的 Error，由上层切换 css 引擎。