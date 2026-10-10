import "./scene.css";
import type { ActionName, SceneEffect, SceneRenderer } from "../core/contract";
import { bus } from "../core/events";

/** 固定种子 mulberry32：所有随机（楼体布局/粒子初速/彩纸颜色）只走这条线，绝不使用 Math.random。 */
const mulberry32 = (seed: number): (() => number) => {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

const NEON = ["#00e5ff", "#ff2079", "#ffb300", "#7c4dff", "#00ffa3"];

const ACTIONS: readonly ActionName[] = [
  "fog", "skyline", "dawn", "fireworks", "laser", "drone",
  "mascot", "spotlight", "confetti", "glitch", "shatter",
];

/** 每帧按 dt 线性泄放（dawn 例外：缓动趋近目标并保持，供色温迁移断言）。 */
const DECAY: Record<ActionName, number> = {
  fog: 0.06, skyline: 0.1, dawn: 0, fireworks: 0.22, laser: 0.18, drone: 0.12,
  mascot: 0.15, spotlight: 0.12, confetti: 0.12, glitch: 0.35, shatter: 0.9,
};

const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);

/* 「2027」5x7 点阵字形（硬编码，非随机）。 */
const GLYPHS: Record<string, readonly string[]> = {
  "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
  "0": [".###.", "#...#", "#.#.#", "#.#.#", "#.#.#", "#...#", ".###."],
  "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
};

const glyphPoints = (): Array<[number, number]> => {
  const word = ["2", "0", "2", "7"];
  const cols = 5;
  const pts: Array<[number, number]> = [];
  word.forEach((ch, ci) => {
    const rows = GLYPHS[ch];
    rows.forEach((row, ry) => {
      for (let cx = 0; cx < cols; cx++) {
        if (row[cx] !== "#") continue;
        pts.push([(ci * (cols + 1) + cx) / (word.length * (cols + 1)), ry / (rows.length - 1)]);
      }
    });
  });
  return pts;
};

interface Shell {
  active: boolean;
  x: number;
  y: number;
  kind: 0 | 1 | 2; // 0 牡丹 / 1 双环 / 2 柳条
  hue: number;
  age: number;
  ringFired: boolean;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  hue: number;
}

interface ConfettiBit {
  el: HTMLElement;
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  spin: number;
  sway: number;
  active: boolean;
}

interface DroneDot {
  el: HTMLElement;
  sx: number;
  sy: number;
  gx: number;
  gy: number;
  phase: number;
}

interface FogBlob {
  x: number;
  y: number;
  r: number;
  speed: number;
  wob: number;
}

/**
 * DOM+Canvas 后备渲染阵营：与 Three 阵营同 SceneEffect 语义、同签名。
 * 零 WebGL、零第三方依赖；全部动画状态只由 `step(dt)` 积分推进，
 * `metrics()` 纯读积分状态 → 同 dt 序列两次重放读数一致（确定度 1.0）。
 */
export class CssRenderer implements SceneRenderer {
  readonly kind = "css" as const;

  private readonly W: number;
  private readonly H: number;
  private readonly rnd: () => number;

  private readonly level: Record<ActionName, number> = {
    fog: 0, skyline: 0, dawn: 0, fireworks: 0, laser: 0, drone: 0,
    mascot: 0, spotlight: 0, confetti: 0, glitch: 0, shatter: 0,
  };
  private dawnTarget = 0;
  private time = 0;
  private shatterAge = 99;
  private fwAlive = 0;

  private raf = 0;
  private last = 0;
  private running = false;
  private disposed = false;
  private readonly offs: Array<() => void> = [];

  private readonly root: HTMLElement;
  private readonly dawnMid: HTMLElement;
  private readonly dawnWarm: HTMLElement;
  private readonly skyLayer: HTMLElement;
  private readonly skyGlow: HTMLElement;
  private readonly laserLayer: HTMLElement;
  private readonly beams: HTMLElement[] = [];
  private readonly droneLayer: HTMLElement;
  private readonly dots: DroneDot[] = [];
  private readonly potLayer: HTMLElement;
  private readonly steam: HTMLElement;
  private readonly spotLayer: HTMLElement;
  private readonly spotCone: HTMLElement;
  private readonly spotPatch: HTMLElement;
  private readonly glitchLayer: HTMLElement;
  private readonly glitchBands: HTMLElement[] = [];
  private readonly glitchRgb: HTMLElement;
  private readonly flash: HTMLElement;
  private readonly shock: HTMLElement;

  private readonly fogACanvas: HTMLCanvasElement;
  private readonly fA: CanvasRenderingContext2D;
  private readonly fB: CanvasRenderingContext2D;
  private readonly fW: CanvasRenderingContext2D;
  private readonly bub: CanvasRenderingContext2D;
  private readonly fogBlobs: FogBlob[] = [];

  private static readonly FW_CAP = 1600;
  private static readonly BUB_CAP = 160;
  private static readonly SHELL_CAP = 48;
  private static readonly CONFETTI = 340;
  private static readonly DRONES = 72;
  private readonly fwPool: Particle[] = [];
  private fwCursor = 0;
  private readonly bubbles: Particle[] = [];
  private bubCursor = 0;
  private readonly shells: Shell[] = [];
  private shellCursor = 0;
  private readonly confetti: ConfettiBit[] = [];

  constructor(mount: HTMLElement) {
    this.W = mount && mount.clientWidth > 0 ? mount.clientWidth : 1280;
    this.H = mount && mount.clientHeight > 0 ? mount.clientHeight : 720;
    this.rnd = mulberry32(0x5eed2027);
    const root = document.createElement("div");
    root.className = "cssc-root";
    this.root = root;
    this.dawnMid = this.add(root, "cssc-dawn cssc-dawn-mid");
    this.dawnWarm = this.add(root, "cssc-dawn cssc-dawn-warm");

    this.skyLayer = this.add(root, "cssc-sky");
    this.buildSkyline();
    this.skyGlow = this.add(this.skyLayer, "cssc-sky-glow");

    const [fogA, fa] = this.addCanvas(root, "cssc-fog cssc-fog-a");
    this.fogACanvas = fogA;
    this.fA = fa;
    this.fB = this.addCanvas(root, "cssc-fog cssc-fog-b")[1];
    for (let i = 0; i < 14; i++) {
      this.fogBlobs.push({
        x: this.rnd() * this.W,
        y: this.H * (0.35 + this.rnd() * 0.6),
        r: 150 + this.rnd() * 260,
        speed: 5 + this.rnd() * 14,
        wob: this.rnd() * Math.PI * 2,
      });
    }

    this.laserLayer = this.add(root, "cssc-laser");
    for (let i = 0; i < 6; i++) {
      const bm = this.add(this.laserLayer, "cssc-beam");
      bm.style.setProperty("--c-neon", NEON[i % NEON.length]);
      bm.style.setProperty("--c-ox", `${8 + i * 15}%`);
      bm.style.animationDelay = `${(i * 0.35).toFixed(2)}s`;
      this.beams.push(bm);
    }

    this.droneLayer = this.add(root, "cssc-drone");
    this.buildDroneMatrix();

    this.potLayer = this.add(root, "cssc-pot");
    this.add(this.potLayer, "cssc-pot-body");
    this.add(this.potLayer, "cssc-pot-rim");
    this.add(this.potLayer, "cssc-pot-grid");
    this.steam = this.add(this.potLayer, "cssc-steam");
    this.bub = this.addCanvas(this.potLayer, "cssc-bubbles")[1];

    this.spotLayer = this.add(root, "cssc-spot");
    this.spotCone = this.add(this.spotLayer, "cssc-spot-cone");
    this.spotPatch = this.add(this.spotLayer, "cssc-spot-patch");

    this.fW = this.addCanvas(root, "cssc-fw")[1];

    const confettiLayer = this.add(root, "cssc-confetti");
    for (let i = 0; i < CssRenderer.CONFETTI; i++) {
      const bit = this.add(confettiLayer, "cssc-bit");
      bit.style.background = NEON[Math.floor(this.rnd() * NEON.length)];
      this.confetti.push({
        el: bit, x: 0, y: -30, vx: 0, vy: 0,
        rot: 0, spin: 0, sway: this.rnd() * Math.PI * 2, active: false,
      });
    }

    this.glitchLayer = this.add(root, "cssc-glitch");
    for (let i = 0; i < 3; i++) {
      const g = this.add(this.glitchLayer, "cssc-glitch-band");
      g.style.setProperty("--c-top", `${18 + i * 27}%`);
      this.glitchBands.push(g);
    }
    this.glitchRgb = this.add(this.glitchLayer, "cssc-glitch-rgb");

    this.flash = this.add(root, "cssc-flash");
    this.shock = this.add(root, "cssc-shock");

    if (mount) mount.appendChild(root);
    for (let i = 0; i < CssRenderer.FW_CAP; i++) {
      this.fwPool.push({ x: 0, y: 0, vx: 0, vy: 0, life: 0, max: 1, hue: 0 });
    }
    for (let i = 0; i < CssRenderer.BUB_CAP; i++) {
      this.bubbles.push({ x: 0, y: 0, vx: 0, vy: 0, life: 0, max: 1, hue: 0 });
    }
    for (let i = 0; i < CssRenderer.SHELL_CAP; i++) {
      this.shells.push({ active: false, x: 0, y: 0, kind: 0, hue: 0, age: 0, ringFired: false });
    }
    this.offs.push(bus.on("agent:command", (cmd: SceneEffect) => this.apply(cmd)));
  }

  /* ── SceneRenderer 契约 ── */
  apply(effect: SceneEffect): void {
    if (this.disposed) return;
    const raw = Number(effect.intensity);
    const intensity = clamp01(Number.isFinite(raw) ? raw : 0);
    const name = effect.action;
    this.level[name] = Math.max(this.level[name], intensity);
    if (name === "dawn") this.dawnTarget = Math.max(this.dawnTarget, intensity);
    else if (name === "fireworks") this.launchShells(intensity);
    else if (name === "confetti") this.launchConfetti(intensity);
    else if (name === "mascot") this.launchBubbles(intensity);
    else if (name === "shatter") this.shatterAge = 0;
  }

  reset(): void {
    for (const a of ACTIONS) this.level[a] = 0;
    this.dawnTarget = 0;
    this.time = 0;
    this.shatterAge = 99;
    this.fwAlive = 0;
    for (const p of this.fwPool) p.life = 0;
    for (const b of this.bubbles) b.life = 0;
    for (const s of this.shells) { s.active = false; s.ringFired = false; }
    for (const c of this.confetti) { c.active = false; c.el.style.opacity = "0"; }
    this.fA.clearRect(0, 0, this.W, this.H);
    this.fB.clearRect(0, 0, this.W, this.H);
    this.fW.clearRect(0, 0, this.W, this.H);
    this.bub.clearRect(0, 0, this.W, this.H);
    this.flash.style.opacity = "0";
    this.shock.style.opacity = "0";
    this.glitchLayer.style.opacity = "0";
    this.root.style.transform = "translate3d(0,0,0)";
  }

  dispose(): void {
    this.stop();
    this.offs.forEach((off) => off());
    this.offs.length = 0;
    this.root.remove();
    this.disposed = true;
  }

  /** 演示用实时循环；评测走 step()/metrics()，不依赖墙钟。 */
  start(): void {
    if (this.running) return;
    this.running = true;
    this.last = performance.now();
    const tick = (now: number): void => {
      if (!this.running) return;
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      this.step(dt);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop(): void {
    this.running = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  /** 状态积分器：dt 秒推进全部缓动、粒子、图层。评测与演示共用。 */
  step(dt: number): void {
    if (this.disposed) return;
    const d = dt > 0 && Number.isFinite(dt) ? dt : 0;
    this.time += d;
    for (const a of ACTIONS) {
      if (a === "dawn") continue;
      const v = this.level[a] - DECAY[a] * d;
      this.level[a] = v > 0 ? v : 0;
    }
    this.level.dawn += (this.dawnTarget - this.level.dawn) * Math.min(1, d / 0.6);
    this.tickSky();
    this.tickDawn();
    this.tickFog(d);
    this.tickLaser();
    this.tickDrones();
    this.tickSpotlight();
    this.tickFireworks(d);
    this.tickPot(d);
    this.tickConfetti(d);
    this.tickGlitch();
    this.tickShatter(d);
  }

  /** 动作名 → 0..1 归一化读数：只由 step 积分出的状态决定。 */
  metrics(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const a of ACTIONS) {
      let v = this.level[a];
      if (a === "skyline") v = Math.max(v, clamp01(v + 0.12 + 0.08 * Math.sin(this.time * 8)));
      if (a === "fireworks") v = Math.max(v, clamp01(this.fwAlive / (CssRenderer.FW_CAP * 0.45)));
      out[a] = clamp01(v);
    }
    return out;
  }

  /** 与 Three 阵营同名的读数入口：App 的 window.__wakeShow.sample() 两阵营通用 */
  sampleState(): Record<string, number> {
    return this.metrics();
  }

  /* ── 图层构建助手 ── */
  private add(parent: HTMLElement, cls: string): HTMLElement {
    const n = document.createElement("div");
    n.className = cls;
    parent.appendChild(n);
    return n;
  }

  private addCanvas(parent: HTMLElement, cls: string): [HTMLCanvasElement, CanvasRenderingContext2D] {
    const c = document.createElement("canvas");
    c.className = cls;
    c.width = this.W;
    c.height = this.H;
    parent.appendChild(c);
    const ctx = c.getContext("2d");
    if (!ctx) throw new Error("CssRenderer: 2d canvas context unavailable");
    return [c, ctx];
  }

  private buildSkyline(): void {
    const count = 96;
    for (let i = 0; i < count; i++) {
      const b = this.add(this.skyLayer, "cssc-building");
      const t = i / count;
      const depth = this.rnd();
      const bw = 9 + depth * 20;
      const bh = (70 + this.rnd() * 240) * (0.5 + t * 0.7);
      const x = t * this.W + (this.rnd() - 0.5) * 26 - bw / 2;
      b.style.width = `${bw.toFixed(1)}px`;
      b.style.height = `${bh.toFixed(1)}px`;
      b.style.transform = `translate3d(${x.toFixed(1)}px,0,0)`;
      b.style.zIndex = String(20 + Math.round(depth * 60));
      const band = this.add(b, "cssc-band");
      band.style.setProperty("--c-neon", NEON[Math.floor(this.rnd() * NEON.length)]);
      band.style.animationDelay = `${(this.rnd() * -2.4).toFixed(2)}s`;
      band.style.animationDuration = `${(1.5 + this.rnd() * 1.5).toFixed(2)}s`;
    }
  }

  private buildDroneMatrix(): void {
    const glyph = glyphPoints();
    for (let i = 0; i < CssRenderer.DRONES; i++) {
      const d = this.add(this.droneLayer, "cssc-dot");
      const g = glyph[i % glyph.length];
      this.dots.push({
        el: d,
        sx: this.rnd() * this.W,
        sy: this.H * (0.04 + this.rnd() * 0.5),
        gx: this.W * (0.18 + g[0] * 0.64),
        gy: this.H * (0.08 + g[1] * 0.24),
        phase: this.rnd() * Math.PI * 2,
      });
    }
  }

  /* ── 帧更新：只改 transform / opacity / Canvas ── */
  private tickSky(): void {
    const lv = this.level.skyline;
    this.skyLayer.style.opacity = clamp01(0.65 + lv * 0.35).toFixed(3);
    const breathe = 0.5 + 0.5 * Math.sin(this.time * 3);
    this.skyGlow.style.opacity = (0.05 + lv * 0.7 * (0.35 + 0.65 * breathe)).toFixed(3);
  }

  private tickDawn(): void {
    const t = this.level.dawn;
    this.dawnMid.style.opacity = (t * 0.9).toFixed(3);
    this.dawnWarm.style.opacity = (Math.max(0, t - 0.45) * 1.6).toFixed(3);
  }

  private tickFog(dt: number): void {
    const op = this.level.fog;
    const fa = this.fA;
    const fbc = this.fB;
    this.fogACanvas.style.opacity = (op * 0.85).toFixed(3);
    const fgb = fbc.canvas;
    fgb.style.opacity = (op * 0.65).toFixed(3);
    if (op < 0.005) return;
    fa.clearRect(0, 0, this.W, this.H);
    fbc.clearRect(0, 0, this.W, this.H);
    this.drawFogLayer(fa, dt, 1, 0.9);
    this.drawFogLayer(fbc, dt, -0.55, 0.6);
  }

  private drawFogLayer(ctx: CanvasRenderingContext2D, dt: number, dir: number, alpha: number): void {
    for (const b of this.fogBlobs) {
      b.x += b.speed * dt * dir;
      if (b.x - b.r > this.W) b.x = -b.r;
      if (b.x + b.r < 0) b.x = this.W + b.r;
      const wob = Math.sin(this.time * 0.5 + b.wob) * 12;
      const grad = ctx.createRadialGradient(b.x, b.y + wob, 0, b.x, b.y + wob, b.r);
      grad.addColorStop(0, `rgba(210,225,245,${(0.32 * alpha).toFixed(3)})`);
      grad.addColorStop(0.55, `rgba(170,190,220,${(0.14 * alpha).toFixed(3)})`);
      grad.addColorStop(1, "rgba(170,190,220,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(b.x, b.y + wob, b.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  private tickLaser(): void {
    const op = this.level.laser;
    this.laserLayer.style.opacity = op.toFixed(3);
    for (let i = 0; i < this.beams.length; i++) {
      const bm = this.beams[i];
      bm.style.setProperty("--c-sway", `${(Math.sin(this.time * 1.7 + i * 1.2) * 26).toFixed(2)}`);
      bm.style.setProperty("--c-stretch", `${(1 + op * 0.5).toFixed(3)}`);
    }
  }

  private tickDrones(): void {
    const mix = this.level.drone;
    this.droneLayer.style.opacity = clamp01(0.12 + mix).toFixed(3);
    for (const d of this.dots) {
      const bx = d.sx + Math.sin(this.time * 0.8 + d.phase) * 16;
      const by = d.sy + Math.cos(this.time * 0.6 + d.phase) * 12;
      const x = bx + (d.gx - bx) * mix;
      const y = by + (d.gy - by) * mix;
      d.el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0)`;
      d.el.style.opacity = (0.25 + mix * 0.75).toFixed(3);
    }
  }

  private tickSpotlight(): void {
    const op = this.level.spotlight;
    this.spotLayer.style.opacity = op.toFixed(3);
    const dx = this.W * (0.5 * (0.5 + 0.5 * Math.sin(this.time * 0.9)) - 0.15);
    const tilt = Math.sin(this.time * 0.9) * 18;
    this.spotCone.style.transform = `translate3d(${dx.toFixed(1)}px,0,0) rotate(${tilt.toFixed(2)}deg)`;
    this.spotPatch.style.transform =
      `translate3d(${dx.toFixed(1)}px,0,0) scale(${(0.7 + op * 0.6).toFixed(3)}, ${(0.8 + op * 0.4).toFixed(3)})`;
  }

  private launchShells(intensity: number): void {
    const shells = 1 + Math.floor(intensity * 5);
    for (let s = 0; s < shells; s++) {
      const sh = this.shells[this.shellCursor];
      this.shellCursor = (this.shellCursor + 1) % CssRenderer.SHELL_CAP;
      sh.active = true;
      sh.ringFired = false;
      sh.kind = Math.floor(this.rnd() * 3) as 0 | 1 | 2;
      sh.hue = this.rnd();
      sh.age = 0;
      const count = 60 + Math.floor(intensity * 260);
      const ox = this.W * (0.12 + this.rnd() * 0.76);
      const oy = this.H * (0.12 + this.rnd() * 0.4);
      sh.x = ox;
      sh.y = oy;
      this.fwCursor = this.emitBurst(sh, ox, oy, count, 0.15 + intensity * 0.25, this.fwCursor, true);
    }
  }

  /** 环形复用粒子池：以 cursor 起始写入 count 粒，返回新游标。 */
  private emitBurst(
    sh: Shell, ox: number, oy: number, count: number,
    spdScale: number, start: number, primary: boolean,
  ): number {
    let cur = start;
    for (let p = 0; p < count; p++) {
      const pt = this.fwPool[cur];
      cur = (cur + 1) % CssRenderer.FW_CAP;
      const ang = (p / count) * Math.PI * 2 + this.rnd() * 0.18;
      const base = sh.kind === 2 ? 35 : sh.kind === 1 && !primary ? 55 : 90;
      const spd = (base + this.rnd() * 170) * (primary ? 1 : 0.55) * (0.8 + spdScale);
      pt.x = ox;
      pt.y = oy;
      pt.vx = Math.cos(ang) * spd;
      pt.vy = Math.sin(ang) * spd - (sh.kind === 2 ? 55 : 0);
      pt.max = sh.kind === 2 ? 2.8 : primary ? 1.7 : 2.2;
      pt.life = pt.max;
      pt.hue = sh.hue;
    }
    return cur;
  }

  private tickFireworks(dt: number): void {
    const ctx = this.fW;
    ctx.clearRect(0, 0, this.W, this.H);
    let alive = 0;
    for (const sh of this.shells) {
      if (!sh.active) continue;
      sh.age += dt;
      if (!sh.ringFired && sh.kind === 1 && sh.age > 0.22) {
        sh.ringFired = true;
        this.fwCursor = this.emitBurst(sh, sh.x, sh.y, 90, 0.5, this.fwCursor, false);
      }
      if (sh.age > 3.2) sh.active = false;
    }
    ctx.globalCompositeOperation = "lighter";
    for (const pt of this.fwPool) {
      if (pt.life <= 0) continue;
      pt.life -= dt;
      pt.vy += 4.5 * dt * (pt.hue > 0.66 ? 0.5 : 1);
      pt.x += pt.vx * dt;
      pt.y += pt.vy * dt;
      pt.vx *= 0.986;
      alive++;
      const a = clamp01(pt.life / pt.max);
      ctx.globalAlpha = a * a;
      ctx.fillStyle = pt.hue < 0.33 ? "#7deaff" : pt.hue < 0.66 ? "#ff5f9e" : "#ffd27f";
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 1.4 + a * 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    this.fwAlive = alive;
  }

  private launchBubbles(intensity: number): void {
    const n = 12 + Math.floor(intensity * 40);
    for (let i = 0; i < n; i++) {
      const b = this.bubbles[this.bubCursor];
      this.bubCursor = (this.bubCursor + 1) % CssRenderer.BUB_CAP;
      b.x = this.W * (0.42 + this.rnd() * 0.16);
      b.y = this.H * 0.84;
      b.vx = (this.rnd() - 0.5) * 14;
      b.vy = -(28 + this.rnd() * 58);
      b.max = 0.9 + this.rnd() * 1.1;
      b.life = b.max;
      b.hue = this.rnd();
    }
  }

  private tickPot(dt: number): void {
    const op = this.level.mascot;
    this.potLayer.style.opacity = clamp01(0.05 + op).toFixed(3);
    this.steam.style.opacity = (op * 0.8 * (0.55 + 0.45 * Math.sin(this.time * 2.2))).toFixed(3);
    const rise = (this.time * 26) % 44;
    this.steam.style.transform = `translate(-50%, ${(-rise).toFixed(1)}px) scaleY(${(1 + op * 0.35).toFixed(3)})`;
    const ctx = this.bub;
    ctx.clearRect(0, 0, this.W, this.H);
    if (op < 0.005) return;
    ctx.globalCompositeOperation = "lighter";
    for (const b of this.bubbles) {
      if (b.life <= 0) continue;
      b.life -= dt;
      b.vy += 10 * dt;
      b.x += b.vx * dt + Math.sin(this.time * 6 + b.hue * 9) * 8 * dt;
      b.y += b.vy * dt;
      const a = clamp01(b.life / b.max);
      ctx.globalAlpha = a * 0.75;
      ctx.strokeStyle = b.hue < 0.5 ? "#ffd27f" : "#ff8a5c";
      ctx.beginPath();
      ctx.arc(b.x, b.y, 1.8 + (1 - a) * 5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  private launchConfetti(intensity: number): void {
    const n = Math.ceil(CssRenderer.CONFETTI * intensity);
    for (let i = 0; i < n; i++) {
      const c = this.confetti[i];
      c.active = true;
      c.x = this.rnd() * this.W;
      c.y = -20 - this.rnd() * this.H * 0.4;
      c.vy = 110 + this.rnd() * 170;
      c.vx = (this.rnd() - 0.5) * 70;
      c.rot = this.rnd() * 360;
      c.spin = (this.rnd() - 0.5) * 720;
    }
  }

  private tickConfetti(dt: number): void {
    const op = this.level.confetti;
    if (op < 0.005) return;
    for (const c of this.confetti) {
      if (!c.active) continue;
      c.y += c.vy * dt;
      c.x += c.vx * dt + Math.sin(this.time * 3 + c.sway) * 26 * dt;
      c.rot += c.spin * dt;
      if (c.y > this.H + 40) { c.active = false; c.el.style.opacity = "0"; continue; }
      c.el.style.opacity = clamp01(op * 1.6).toFixed(3);
      c.el.style.transform =
        `translate3d(${c.x.toFixed(1)}px,${c.y.toFixed(1)}px,0) rotate3d(0.6,1,0.3,${c.rot.toFixed(1)}deg)`;
    }
  }

  private tickGlitch(): void {
    const op = this.level.glitch;
    this.glitchLayer.style.opacity = op.toFixed(3);
    if (op < 0.005) return;
    for (let i = 0; i < this.glitchBands.length; i++) {
      const n = Math.sin(this.time * 43 + i * 12.9898) * 43758.5453;
      const j = n - Math.floor(n);
      const burst = Math.sin(this.time * 7 + i) * 0.5 + 0.5;
      const off = (j - 0.5) * 90 * op * (0.4 + burst);
      this.glitchBands[i].style.transform = `translate3d(${off.toFixed(1)}px,0,0)`;
      this.glitchBands[i].style.opacity = (0.5 + 0.5 * burst).toFixed(3);
    }
    const sep = (0.5 + 0.5 * Math.sin(this.time * 37)) * op * 5;
    this.glitchRgb.style.filter =
      `drop-shadow(${sep.toFixed(1)}px 0 0 rgba(255,32,121,0.75)) drop-shadow(${(-sep).toFixed(1)}px 0 0 rgba(0,229,255,0.75))`;
  }

  private tickShatter(dt: number): void {
    this.shatterAge += dt;
    const p = this.shatterAge;
    if (p >= 0.8) {
      if (this.flash.style.opacity !== "0") {
        this.flash.style.opacity = "0";
        this.shock.style.opacity = "0";
        this.root.style.transform = "translate3d(0,0,0)";
      }
      return;
    }
    const flash = p < 0.08 ? p / 0.08 : clamp01(1 - (p - 0.08) / 0.18);
    this.flash.style.opacity = (flash * 0.9).toFixed(3);
    const ring = clamp01(p / 0.6);
    this.shock.style.opacity = (1 - ring).toFixed(3);
    this.shock.style.transform = `translate(-50%,-50%) scale(${(0.15 + ring * 7).toFixed(3)})`;
    const shake = p < 0.3 ? (1 - p / 0.3) * 7 : 0;
    const dx = Math.sin(this.shatterAge * 140) * shake;
    const dy = Math.cos(this.shatterAge * 120) * shake;
    this.root.style.transform = `translate3d(${dx.toFixed(2)}px,${dy.toFixed(2)}px,0)`;
  }
}