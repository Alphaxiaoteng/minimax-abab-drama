import * as THREE from "three";
import { softDotTexture } from "./texture";
import type { Rng } from "./rng";

const BOUNDS = { x: 90, yMin: -2, yMax: 22, zMin: -80, zMax: 30 };

/** 平流雾粒子场：沿江漂移，能量 0..1 线性控制浓度/膨胀（上限内不遮死霓虹） */
export class FogField {
  readonly points: THREE.Points;
  private material: THREE.PointsMaterial;
  private velocities: Float32Array;

  constructor(count: number, rng: Rng) {
    const positions = new Float32Array(count * 3);
    this.velocities = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = rng.range(-BOUNDS.x, BOUNDS.x);
      positions[i * 3 + 1] = rng.range(BOUNDS.yMin, BOUNDS.yMax);
      positions[i * 3 + 2] = rng.range(BOUNDS.zMin, BOUNDS.zMax);
      this.velocities[i] = rng.range(0.4, 1.8);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.material = new THREE.PointsMaterial({
      size: 16,
      map: softDotTexture(),
      color: 0x8fa3c8,
      transparent: true,
      opacity: 0.1,
      depthWrite: false,
    });
    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
  }

  update(dt: number, energy: number): void {
    const pos = this.points.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = pos.array as Float32Array;
    for (let i = 0; i < this.velocities.length; i++) {
      let x = arr[i * 3] + this.velocities[i] * dt;
      if (x > BOUNDS.x) x = -BOUNDS.x;
      arr[i * 3] = x;
    }
    pos.needsUpdate = true;
    this.material.opacity += (0.1 + energy * 0.4 - this.material.opacity) * Math.min(1, dt * 2.5);
    this.material.size = 16 + energy * 8;
  }

  reset(): void {
    this.material.opacity = 0.1;
    this.material.size = 16;
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.material.dispose();
  }
}