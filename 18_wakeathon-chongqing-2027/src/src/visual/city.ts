import * as THREE from "three";
import { softDotTexture } from "./texture";
import { NEON } from "./palette";
import type { Rng } from "./rng";

interface BuildingSpec {
  x: number;
  y: number;
  z: number;
  w: number;
  h: number;
  d: number;
  neon: THREE.Color;
}

const TIERS = [
  { zRange: [-78, -50] as const, base: 7, count: 48, hMul: 1.35 },
  { zRange: [-50, -26] as const, base: 2.5, count: 58, hMul: 1.0 },
  { zRange: [-26, -4] as const, base: -1.5, count: 52, hMul: 0.75 },
];

/** 三层吊脚楼天际线 + 嘉陵江水面：深色楼体、霓虹灯带、窗光点（散布走确定性 Rng） */
export class City {
  readonly group = new THREE.Group();
  private bodyMat: THREE.MeshStandardMaterial;
  private bandMat: THREE.MeshBasicMaterial;
  private windowsMat: THREE.PointsMaterial;
  private riverMat: THREE.MeshStandardMaterial;
  private bodies: THREE.InstancedMesh;
  private bands: THREE.InstancedMesh;
  private windows: THREE.Points;
  private river: THREE.Mesh;
  private pulse = 0;

  constructor(rng: Rng) {
    const specs: BuildingSpec[] = [];
    for (const tier of TIERS) {
      for (let i = 0; i < tier.count; i++) {
        const x = rng.range(-68, 68);
        const centerBoost = 1 + 0.55 * Math.exp(-((x / 34) ** 2));
        const h = rng.range(3, 15) * tier.hMul * centerBoost;
        specs.push({
          x,
          y: tier.base + rng.range(0, 2.2),
          z: rng.range(tier.zRange[0], tier.zRange[1]),
          w: rng.range(1.6, 4.2),
          h,
          d: rng.range(1.6, 4.2),
          neon: new THREE.Color(NEON[rng.int(NEON.length)]),
        });
      }
    }

    const bodyGeo = new THREE.BoxGeometry(1, 1, 1);
    this.bodyMat = new THREE.MeshStandardMaterial({ color: 0x0c1220, roughness: 0.85, metalness: 0.15 });
    this.bodies = new THREE.InstancedMesh(bodyGeo, this.bodyMat, specs.length);
    const bandGeo = new THREE.BoxGeometry(1, 0.32, 1);
    this.bandMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    this.bands = new THREE.InstancedMesh(bandGeo, this.bandMat, specs.length);

    const matrix = new THREE.Matrix4();
    const winPositions: number[] = [];
    specs.forEach((s, i) => {
      matrix.makeScale(s.w, s.h, s.d);
      matrix.setPosition(s.x, s.y + s.h / 2, s.z);
      this.bodies.setMatrixAt(i, matrix);

      matrix.makeScale(s.w + 0.15, 1, s.d + 0.15);
      matrix.setPosition(s.x, s.y + s.h + 0.2, s.z);
      this.bands.setMatrixAt(i, matrix);
      this.bands.setColorAt(i, s.neon);

      const winCount = 4 + rng.int(6);
      for (let w = 0; w < winCount; w++) {
        const face = rng.next() < 0.5;
        winPositions.push(
          s.x + (face ? (rng.next() - 0.5) * s.w : (rng.next() < 0.5 ? -1 : 1) * (s.w / 2 + 0.06)),
          s.y + rng.range(0.8, s.h - 0.5),
          s.z + (face ? (rng.next() < 0.5 ? -1 : 1) * (s.d / 2 + 0.06) : (rng.next() - 0.5) * s.d),
        );
      }
    });
    if (this.bands.instanceColor) this.bands.instanceColor.needsUpdate = true;

    const winGeo = new THREE.BufferGeometry();
    winGeo.setAttribute("position", new THREE.Float32BufferAttribute(winPositions, 3));
    this.windowsMat = new THREE.PointsMaterial({
      size: 0.9,
      map: softDotTexture(),
      color: 0xffd27a,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    });
    this.windows = new THREE.Points(winGeo, this.windowsMat);

    this.riverMat = new THREE.MeshStandardMaterial({ color: 0x050a16, roughness: 0.55, metalness: 0.25 });
    this.river = new THREE.Mesh(new THREE.PlaneGeometry(320, 170), this.riverMat);
    this.river.rotation.x = -Math.PI / 2;
    this.river.position.set(0, -3.4, 20);

    this.group.add(this.bodies, this.bands, this.windows, this.river);
  }

  /** skyline 能量 0..1 → 灯带脉冲幅度 */
  setPulse(energy: number): void {
    this.pulse = Math.min(1.6, energy * 1.6);
  }

  update(t: number): void {
    this.bandMat.color.setScalar(1 + Math.sin(t * 8) * 0.9 * this.pulse);
    this.windowsMat.opacity = 0.7 + this.pulse * 0.25 + Math.sin(t * 3.1) * 0.05 * this.pulse;
  }

  dispose(): void {
    this.bodies.geometry.dispose();
    this.bodyMat.dispose();
    this.bands.geometry.dispose();
    this.bandMat.dispose();
    this.windows.geometry.dispose();
    this.windowsMat.dispose();
    this.river.geometry.dispose();
    this.riverMat.dispose();
  }
}