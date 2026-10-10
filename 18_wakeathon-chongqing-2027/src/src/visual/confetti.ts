import * as THREE from "three";
import { confettiTexture } from "./texture";
import { NEON } from "./palette";
import type { Rng } from "./rng";

/**
 * 彩纸片：InstancedMesh 小面片，俯冲 + 三轴翻滚（每帧合成矩阵，scratch 预分配）。
 * 能量驱动发射速率；容量固定，死亡片缩到 0 等待复用。
 */
export class ConfettiRain {
  readonly mesh: THREE.InstancedMesh;
  private pos: Float32Array;
  private vel: Float32Array;
  private rot: Float32Array;
  private rotVel: Float32Array;
  private life: Float32Array;
  private capacity: number;
  private cursor = 0;
  private rng: Rng;
  private scratchMatrix = new THREE.Matrix4();
  private scratchQuat = new THREE.Quaternion();
  private scratchEuler = new THREE.Euler();
  private scratchScale = new THREE.Vector3();
  private scratchPos = new THREE.Vector3();

  constructor(capacity: number, rng: Rng) {
    this.capacity = capacity;
    this.rng = rng;
    this.pos = new Float32Array(capacity * 3);
    this.vel = new Float32Array(capacity * 3);
    this.rot = new Float32Array(capacity * 3);
    this.rotVel = new Float32Array(capacity * 3);
    this.life = new Float32Array(capacity);

    const geo = new THREE.PlaneGeometry(0.5, 0.32);
    const mat = new THREE.MeshBasicMaterial({
      map: confettiTexture(),
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    this.mesh = new THREE.InstancedMesh(geo, mat, capacity);
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.mesh.frustumCulled = false;
    const c = new THREE.Color();
    for (let i = 0; i < capacity; i++) {
      c.setHex(NEON[rng.int(NEON.length)]);
      this.mesh.setColorAt(i, c);
    }
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }

  private spawn(): void {
    const i = this.cursor;
    this.cursor = (this.cursor + 1) % this.capacity;
    this.pos[i * 3] = this.rng.range(-60, 60);
    this.pos[i * 3 + 1] = this.rng.range(42, 55);
    this.pos[i * 3 + 2] = this.rng.range(-70, 10);
    this.vel[i * 3] = this.rng.range(-2, 2);
    this.vel[i * 3 + 1] = this.rng.range(-14, -7);
    this.vel[i * 3 + 2] = this.rng.range(-2, 2);
    this.rot[i * 3] = this.rng.range(0, Math.PI * 2);
    this.rot[i * 3 + 1] = this.rng.range(0, Math.PI * 2);
    this.rot[i * 3 + 2] = this.rng.range(0, Math.PI * 2);
    this.rotVel[i * 3] = this.rng.range(-6, 6);
    this.rotVel[i * 3 + 1] = this.rng.range(-6, 6);
    this.rotVel[i * 3 + 2] = this.rng.range(-4, 4);
    this.life[i] = this.rng.range(3.5, 6);
  }

  update(dt: number, energy: number): void {
    for (let s = 0; s < Math.round(energy * 70 * dt); s++) this.spawn();

    for (let i = 0; i < this.capacity; i++) {
      const l = this.life[i];
      if (l <= 0) {
        this.scratchMatrix.makeScale(0, 0, 0);
        this.mesh.setMatrixAt(i, this.scratchMatrix);
        continue;
      }
      this.life[i] = l - dt;
      this.vel[i * 3 + 1] += -2.5 * dt; // 俯冲加速
      this.vel[i * 3] += Math.sin(this.life[i] * 3 + i) * 1.5 * dt; // 飘摆
      this.pos[i * 3] += this.vel[i * 3] * dt;
      this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
      this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      this.rot[i * 3] += this.rotVel[i * 3] * dt;
      this.rot[i * 3 + 1] += this.rotVel[i * 3 + 1] * dt;
      this.rot[i * 3 + 2] += this.rotVel[i * 3 + 2] * dt;
      const fade = Math.min(1, this.life[i] / 1.2);
      this.scratchEuler.set(this.rot[i * 3], this.rot[i * 3 + 1], this.rot[i * 3 + 2]);
      this.scratchQuat.setFromEuler(this.scratchEuler);
      this.scratchPos.set(this.pos[i * 3], this.pos[i * 3 + 1], this.pos[i * 3 + 2]);
      this.scratchScale.setScalar(0.7 + 0.6 * fade);
      this.scratchMatrix.compose(this.scratchPos, this.scratchQuat, this.scratchScale);
      this.mesh.setMatrixAt(i, this.scratchMatrix);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  reset(): void {
    this.life.fill(0);
    for (let i = 0; i < this.capacity; i++) {
      this.scratchMatrix.makeScale(0, 0, 0);
      this.mesh.setMatrixAt(i, this.scratchMatrix);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    (this.mesh.material as THREE.Material).dispose();
  }
}