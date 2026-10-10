import * as THREE from "three";
import { softDotTexture } from "./texture";
import type { Rng } from "./rng";

/**
 * 火锅图腾：铜锅轮廓（发光环 + 深色锅体）、沸腾泡泡粒子、蒸汽柱。
 * 出现在画面下三分之一；能量 0..1 驱动锅体亮度、冒泡速率与蒸汽浓度。
 * 泡泡/蒸汽为固定池，update 只写 typed array，无逐帧分配。
 */
export class HotpotMascot {
  readonly group = new THREE.Group();
  private bubbles: THREE.Points;
  private steam: THREE.Points;
  private bubblePos: Float32Array;
  private bubbleVel: Float32Array;
  private bubbleLife: Float32Array;
  private bubbleColors: Float32Array;
  private steamPos: Float32Array;
  private steamLife: Float32Array;
  private steamSeeds: Float32Array;
  private steamColors: Float32Array;
  private ringMat: THREE.MeshBasicMaterial;
  private brothMat: THREE.MeshBasicMaterial;
  private bubbleCount: number;
  private steamCount: number;
  private rng: Rng;

  constructor(bubbleCount: number, steamCount: number, rng: Rng) {
    this.bubbleCount = bubbleCount;
    this.steamCount = steamCount;
    this.rng = rng;

    // 锅位于画面下三分之一偏右：近景、江面之上台地
    const potX = 14;
    const potY = -2.2;
    const potZ = 24;

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(5, 0.45, 10, 48),
      new THREE.MeshBasicMaterial({
        color: 0xffb300,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.ringMat = ring.material as THREE.MeshBasicMaterial;
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(potX, potY, potZ);

    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(5, 3.6, 2.6, 32, 1, true),
      new THREE.MeshStandardMaterial({
        color: 0x5a3a1a,
        roughness: 0.4,
        metalness: 0.8,
        side: THREE.DoubleSide,
      }),
    );
    body.position.set(potX, potY - 1.4, potZ);

    const broth = new THREE.Mesh(
      new THREE.CircleGeometry(4.7, 32),
      new THREE.MeshBasicMaterial({
        color: 0xff2079,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.brothMat = broth.material as THREE.MeshBasicMaterial;
    broth.rotation.x = -Math.PI / 2;
    broth.position.set(potX, potY + 0.05, potZ);

    this.bubblePos = new Float32Array(bubbleCount * 3);
    this.bubbleVel = new Float32Array(bubbleCount * 3);
    this.bubbleLife = new Float32Array(bubbleCount);
    this.bubbleColors = new Float32Array(bubbleCount * 3);
    const bubbleGeo = new THREE.BufferGeometry();
    bubbleGeo.setAttribute("position", new THREE.BufferAttribute(this.bubblePos, 3));
    bubbleGeo.setAttribute("color", new THREE.BufferAttribute(this.bubbleColors, 3));
    this.bubbles = new THREE.Points(
      bubbleGeo,
      new THREE.PointsMaterial({
        size: 0.5,
        map: softDotTexture(),
        vertexColors: true,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    this.bubbles.frustumCulled = false;

    this.steamPos = new Float32Array(steamCount * 3);
    this.steamLife = new Float32Array(steamCount);
    this.steamSeeds = new Float32Array(steamCount);
    this.steamColors = new Float32Array(steamCount * 3);
    const steamGeo = new THREE.BufferGeometry();
    steamGeo.setAttribute("position", new THREE.BufferAttribute(this.steamPos, 3));
    steamGeo.setAttribute("color", new THREE.BufferAttribute(this.steamColors, 3));
    this.steam = new THREE.Points(
      steamGeo,
      new THREE.PointsMaterial({
        size: 3.2,
        map: softDotTexture(),
        vertexColors: true,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
      }),
    );
    this.steam.frustumCulled = false;
    for (let i = 0; i < steamCount; i++) this.steamSeeds[i] = rng.range(0, Math.PI * 2);

    this.group.add(ring, body, broth, this.bubbles, this.steam);
  }

  private spawnBubble(): void {
    for (let i = 0; i < this.bubbleCount; i++) {
      if (this.bubbleLife[i] > 0) continue;
      const ang = this.rng.range(0, Math.PI * 2);
      const r = this.rng.range(0, 4);
      this.bubblePos[i * 3] = 14 + Math.cos(ang) * r;
      this.bubblePos[i * 3 + 1] = -2.2;
      this.bubblePos[i * 3 + 2] = 24 + Math.sin(ang) * r;
      this.bubbleVel[i * 3] = this.rng.range(-0.3, 0.3);
      this.bubbleVel[i * 3 + 1] = this.rng.range(1.2, 2.6);
      this.bubbleVel[i * 3 + 2] = this.rng.range(-0.3, 0.3);
      this.bubbleLife[i] = this.rng.range(0.5, 1.1);
      return;
    }
  }

  update(elapsed: number, dt: number, energy: number): void {
    const pulse = 0.75 + 0.25 * Math.sin(elapsed * 7);
    this.ringMat.opacity = energy * 0.9 * pulse;
    this.brothMat.opacity = energy * 0.6 * pulse;

    const spawnRate = energy * 90;
    for (let s = 0; s < Math.round(spawnRate * dt); s++) this.spawnBubble();

    for (let i = 0; i < this.bubbleCount; i++) {
      const l = this.bubbleLife[i];
      if (l <= 0) {
        this.bubbleColors[i * 3] = 0;
        this.bubbleColors[i * 3 + 1] = 0;
        this.bubbleColors[i * 3 + 2] = 0;
        continue;
      }
      this.bubbleLife[i] = l - dt;
      const k = Math.max(0, this.bubbleLife[i]);
      this.bubblePos[i * 3] += this.bubbleVel[i * 3] * dt;
      this.bubblePos[i * 3 + 1] += this.bubbleVel[i * 3 + 1] * dt;
      this.bubblePos[i * 3 + 2] += this.bubbleVel[i * 3 + 2] * dt;
      this.bubbleColors[i * 3] = 1 * k;
      this.bubbleColors[i * 3 + 1] = 0.55 * k;
      this.bubbleColors[i * 3 + 2] = 0.15 * k;
    }
    this.bubbles.geometry.getAttribute("position").needsUpdate = true;
    this.bubbles.geometry.getAttribute("color").needsUpdate = true;

    for (let i = 0; i < this.steamCount; i++) {
      const l = this.steamLife[i];
      if (l <= 0) {
        if (energy > 0.05 && this.rng.next() < energy * dt * 18) {
          this.steamLife[i] = this.rng.range(1.6, 2.8);
          this.steamPos[i * 3] = 14 + this.rng.range(-3, 3);
          this.steamPos[i * 3 + 1] = -2;
          this.steamPos[i * 3 + 2] = 24 + this.rng.range(-3, 3);
        }
        this.steamColors[i * 3] = 0;
        this.steamColors[i * 3 + 1] = 0;
        this.steamColors[i * 3 + 2] = 0;
        continue;
      }
      this.steamLife[i] = l - dt;
      const k = Math.max(0, this.steamLife[i]);
      this.steamPos[i * 3 + 1] += dt * 2.4;
      this.steamPos[i * 3] += Math.sin(elapsed * 1.3 + this.steamSeeds[i]) * dt * 0.8;
      const fade = Math.min(k, 1) * energy * 0.7;
      this.steamColors[i * 3] = 0.75 * fade;
      this.steamColors[i * 3 + 1] = 0.8 * fade;
      this.steamColors[i * 3 + 2] = 0.9 * fade;
    }
    this.steam.geometry.getAttribute("position").needsUpdate = true;
    this.steam.geometry.getAttribute("color").needsUpdate = true;
  }

  reset(): void {
    this.bubbleLife.fill(0);
    this.bubbleColors.fill(0);
    this.steamLife.fill(0);
    this.steamColors.fill(0);
    this.ringMat.opacity = 0;
    this.brothMat.opacity = 0;
  }

  dispose(): void {
    this.bubbles.geometry.dispose();
    (this.bubbles.material as THREE.Material).dispose();
    this.steam.geometry.dispose();
    (this.steam.material as THREE.Material).dispose();
    this.group.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        (o.material as THREE.Material).dispose();
      }
    });
  }
}