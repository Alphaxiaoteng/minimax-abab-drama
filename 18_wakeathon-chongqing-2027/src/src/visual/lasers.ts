import * as THREE from "three";
import { NEON } from "./palette";

/**
 * 体积光扇面：从江面/楼顶斜射天空的加色锥面，能量驱动亮度、时间驱动摆动。
 * 共享一份锥体几何（构造时预调朝向），update 只改 rotation/opacity，无逐帧分配。
 */
export class LaserFan {
  readonly group = new THREE.Group();
  private geometry = new THREE.ConeGeometry(3, 60, 6, 1, true);
  private beams: THREE.Mesh[] = [];
  private mats: THREE.MeshBasicMaterial[] = [];

  constructor(count: number) {
    // 默认 ConeGeometry 顶面（宽口）朝 +y：旋转 π 使尖端朝上作为天空端，
    // 再平移使宽口底（光源）落在原点，扇面自地面向上展开
    this.geometry.rotateX(Math.PI);
    this.geometry.translate(0, 30, 0);
    for (let i = 0; i < count; i++) {
      const mat = new THREE.MeshBasicMaterial({
        color: NEON[i % NEON.length],
        transparent: true,
        opacity: 0,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
      });
      const beam = new THREE.Mesh(this.geometry, mat);
      beam.position.set((i - (count - 1) / 2) * 14, -2, -46);
      this.beams.push(beam);
      this.mats.push(mat);
      this.group.add(beam);
    }
  }

  update(elapsed: number, energy: number): void {
    for (let i = 0; i < this.beams.length; i++) {
      const phase = elapsed * 0.6 + i * 1.2;
      const beam = this.beams[i];
      beam.rotation.z = Math.sin(phase) * 0.5;
      beam.rotation.x = Math.cos(phase * 0.8) * 0.35;
      const flicker = 0.7 + 0.3 * Math.sin(elapsed * 9 + i);
      this.mats[i].opacity = energy * 0.5 * flicker;
    }
  }

  reset(): void {
    for (const m of this.mats) m.opacity = 0;
  }

  dispose(): void {
    this.geometry.dispose();
    for (const m of this.mats) m.dispose();
  }
}