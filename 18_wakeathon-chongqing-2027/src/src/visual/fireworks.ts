import * as THREE from "three";
import { softDotTexture } from "./texture";
import { NEON } from "./palette";
import type { Rng } from "./rng";

type BurstKind = "peony" | "ring" | "willow";

interface BurstProfile {
  speed: [number, number];
  gravity: number;
  life: [number, number];
  drag: number;
}

const PROFILES: Record<BurstKind, BurstProfile> = {
  peony: { speed: [7, 15], gravity: 4.5, life: [1.5, 2.4], drag: 0.35 },
  ring: { speed: [11, 12.5], gravity: 3.2, life: [1.8, 2.6], drag: 0.2 },
  willow: { speed: [4, 8], gravity: 9.0, life: [3.0, 4.2], drag: 0.5 },
};

const KINDS: readonly BurstKind[] = ["peony", "ring", "willow"];

/** 加色烟花粒子池：牡丹 / 双环 / 柳条三种爆型，初速与重力各型不同；方向取自确定性 Rng */
export class FireworksShow {
  readonly points: THREE.Points;
  private positions: Float32Array;
  private velocities: Float32Array;
  private colors: Float32Array;
  private baseColors: Float32Array;
  private gravity: Float32Array;
  private drag: Float32Array;
  private life: Float32Array;
  private maxLife: Float32Array;
  private capacity: number;
  private cursor = 0;
  private rng: Rng;
  private scratchColor = new THREE.Color();

  constructor(capacity: number, rng: Rng) {
    this.capacity = capacity;
    this.rng = rng;
    this.positions = new Float32Array(capacity * 3);
    this.velocities = new Float32Array(capacity * 3);
    this.colors = new Float32Array(capacity * 3);
    this.baseColors = new Float32Array(capacity * 3);
    this.gravity = new Float32Array(capacity);
    this.drag = new Float32Array(capacity);
    this.life = new Float32Array(capacity);
    this.maxLife = new Float32Array(capacity);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(this.colors, 3));
    const mat = new THREE.PointsMaterial({
      size: 0.55,
      map: softDotTexture(),
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, mat);
    this.points.frustumCulled = false;
  }

  spawnBurst(intensity: number): void {
    const count = Math.round(90 + intensity * 260);
    const kind = KINDS[this.rng.int(KINDS.length)];
    const p = PROFILES[kind];
    const ox = this.rng.range(-55, 55);
    const oy = this.rng.range(22, 42);
    const oz = this.rng.range(-75, -32);
    this.scratchColor.setHex(NEON[this.rng.int(NEON.length)]);
    const cr = this.scratchColor.r;
    const cg = this.scratchColor.g;
    const cb = this.scratchColor.b;
    for (let n = 0; n < count; n++) {
      const i = this.cursor;
      this.cursor = (this.cursor + 1) % this.capacity;
      const az = this.rng.range(0, Math.PI * 2);
      const el = kind === "ring" ? Math.PI / 2 + this.rng.range(-0.14, 0.14) : Math.acos(this.rng.range(-1, 1));
      const speed = kind === "ring" && this.rng.next() < 0.5 ? p.speed[0] : this.rng.range(p.speed[0], p.speed[1]);
      this.positions[i * 3] = ox;
      this.positions[i * 3 + 1] = oy;
      this.positions[i * 3 + 2] = oz;
      this.velocities[i * 3] = Math.sin(el) * Math.cos(az) * speed;
      this.velocities[i * 3 + 1] = Math.cos(el) * speed * (kind === "willow" ? 0.6 : 1);
      this.velocities[i * 3 + 2] = Math.sin(el) * Math.sin(az) * speed;
      const tint = this.rng.range(0.75, 1);
      this.baseColors[i * 3] = cr * tint;
      this.baseColors[i * 3 + 1] = cg * tint;
      this.baseColors[i * 3 + 2] = cb * tint;
      const life = this.rng.range(p.life[0], p.life[1]);
      this.life[i] = life;
      this.maxLife[i] = life;
      this.gravity[i] = p.gravity;
      this.drag[i] = p.drag;
    }
  }

  /** 多弹连发：wake 时刻与高能量烟花用 */
  volley(intensity: number, shells: number): void {
    for (let s = 0; s < shells; s++) this.spawnBurst(intensity);
  }

  update(dt: number): void {
    for (let i = 0; i < this.capacity; i++) {
      const l = this.life[i];
      if (l <= 0) {
        this.colors[i * 3] = 0;
        this.colors[i * 3 + 1] = 0;
        this.colors[i * 3 + 2] = 0;
        continue;
      }
      this.life[i] = l - dt;
      const k = Math.max(0, this.life[i] / this.maxLife[i]);
      const fade = k * k;
      this.velocities[i * 3 + 1] -= this.gravity[i] * dt;
      const damp = Math.max(0, 1 - this.drag[i] * dt);
      for (let a = 0; a < 3; a++) {
        const j = i * 3 + a;
        this.velocities[j] *= damp;
        this.positions[j] += this.velocities[j] * dt;
        this.colors[j] = this.baseColors[j] * fade;
      }
    }
    this.points.geometry.getAttribute("position").needsUpdate = true;
    this.points.geometry.getAttribute("color").needsUpdate = true;
  }

  reset(): void {
    this.life.fill(0);
    this.colors.fill(0);
    this.points.geometry.getAttribute("position").needsUpdate = true;
    this.points.geometry.getAttribute("color").needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    (this.points.material as THREE.Material).dispose();
  }
}