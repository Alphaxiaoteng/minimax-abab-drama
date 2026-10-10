import * as THREE from "three";
import { softDotTexture } from "./texture";
import { NEON } from "./palette";
import type { Rng } from "./rng";

/**
 * 无人机编队：Points + 目标位姿 lerp。
 * 能量 0 → 散射云；能量 1 → 「2027」文字阵型。全部预分配，每帧只写 typed array。
 */
export class DroneSquadron {
  readonly points: THREE.Points;
  private scatter: Float32Array;
  private formation: Float32Array;
  private phases: Float32Array;
  private baseColors: Float32Array;
  private capacity: number;

  constructor(capacity: number, rng: Rng, text = "2027") {
    this.capacity = capacity;
    this.scatter = new Float32Array(capacity * 3);
    this.formation = new Float32Array(capacity * 3);
    this.phases = new Float32Array(capacity);
    this.baseColors = new Float32Array(capacity * 3);
    const positions = new Float32Array(capacity * 3);

    this.buildFormation(rng, text);
    const c = new THREE.Color();
    for (let i = 0; i < capacity; i++) {
      const j = i * 3;
      const r = rng.range(6, 34);
      const az = rng.range(0, Math.PI * 2);
      const el = Math.acos(rng.range(-1, 1));
      this.scatter[j] = Math.sin(el) * Math.cos(az) * r;
      this.scatter[j + 1] = 30 + Math.cos(el) * r * 0.6;
      this.scatter[j + 2] = -44 + Math.sin(el) * Math.sin(az) * r;
      this.phases[i] = rng.range(0, Math.PI * 2);
      c.setHex(NEON[rng.int(NEON.length)]);
      this.baseColors[j] = c.r;
      this.baseColors[j + 1] = c.g;
      this.baseColors[j + 2] = c.b;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(this.baseColors.slice(), 3));
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

  /** 从画布采样文字亮点，确定性映射为阵型目标位 */
  private buildFormation(rng: Rng, text: string): void {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 96;
    const ctx = canvas.getContext("2d");
    const pts: number[] = [];
    if (ctx) {
      ctx.font = "bold 74px sans-serif";
      ctx.fillStyle = "#fff";
      ctx.textBaseline = "middle";
      ctx.fillText(text, 6, 52);
      const data = ctx.getImageData(0, 0, 320, 96).data;
      for (let y = 0; y < 96; y += 2) {
        for (let x = 0; x < 320; x += 2) {
          if (data[(y * 320 + x) * 4 + 3] > 128) pts.push(x, y);
        }
      }
    }
    const samples = pts.length / 2;
    for (let i = 0; i < this.capacity; i++) {
      let px: number;
      let py: number;
      if (samples > 0) {
        const s = rng.int(samples) * 2;
        px = pts[s];
        py = pts[s + 1];
      } else {
        px = rng.range(0, 320);
        py = rng.range(30, 66);
      }
      this.formation[i * 3] = ((px + 0.5) / 320 - 0.5) * 54;
      this.formation[i * 3 + 1] = 30 + (0.5 - (py + 0.5) / 96) * 16;
      this.formation[i * 3 + 2] = -48 + rng.range(-1.5, 1.5);
    }
  }

  update(elapsed: number, energy: number): void {
    const mix = THREE.MathUtils.smoothstep(energy, 0.15, 0.9);
    const pos = this.points.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = pos.array as Float32Array;
    const col = this.points.geometry.getAttribute("color") as THREE.BufferAttribute;
    const carr = col.array as Float32Array;
    for (let i = 0; i < this.capacity; i++) {
      const j = i * 3;
      const bob = Math.sin(elapsed * 2.2 + this.phases[i]) * 0.4;
      arr[j] = this.scatter[j] + (this.formation[j] - this.scatter[j]) * mix;
      arr[j + 1] = this.scatter[j + 1] + (this.formation[j + 1] - this.scatter[j + 1]) * mix + bob;
      arr[j + 2] = this.scatter[j + 2] + (this.formation[j + 2] - this.scatter[j + 2]) * mix;
      const tw = 0.55 + 0.45 * Math.sin(elapsed * 6 + this.phases[i] * 3);
      const bright = (0.15 + energy * 0.85) * tw;
      carr[j] = this.baseColors[j] * bright;
      carr[j + 1] = this.baseColors[j + 1] * bright;
      carr[j + 2] = this.baseColors[j + 2] * bright;
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
  }

  reset(): void {
    // 位置/亮度纯能量驱动，能量归零后下一帧自动回散云
  }

  dispose(): void {
    this.points.geometry.dispose();
    (this.points.material as THREE.Material).dispose();
  }
}