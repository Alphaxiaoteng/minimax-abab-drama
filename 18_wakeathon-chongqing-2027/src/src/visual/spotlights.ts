import * as THREE from "three";

/**
 * 追光：沿闭合轨迹滑动的锥形光束 + 江面/地面亮斑。
 * 轨迹由 elapsed 参数化（Lissajous），能量驱动可见性，无逐帧分配。
 */
export class SpotlightRig {
  readonly group = new THREE.Group();
  private beam: THREE.Mesh;
  private spot: THREE.Mesh;
  private beamMat: THREE.MeshBasicMaterial;
  private spotMat: THREE.MeshBasicMaterial;
  private up = new THREE.Vector3(0, 1, 0);
  private dir = new THREE.Vector3();
  private mid = new THREE.Vector3();

  constructor(private centerX = 0, private centerZ = 4) {
    const beamGeo = new THREE.ConeGeometry(5, 1, 16, 1, true);
    beamGeo.translate(0, -0.5, 0);
    this.beamMat = new THREE.MeshBasicMaterial({
      color: 0x00e5ff,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    this.beam = new THREE.Mesh(beamGeo, this.beamMat);

    this.spotMat = new THREE.MeshBasicMaterial({
      color: 0x9ff4ff,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.spot = new THREE.Mesh(new THREE.CircleGeometry(1, 24), this.spotMat);
    this.spot.rotation.x = -Math.PI / 2;

    this.group.add(this.beam, this.spot);
  }

  update(elapsed: number, energy: number): void {
    const gx = this.centerX + Math.sin(elapsed * 0.7) * 26;
    const gz = this.centerZ + Math.cos(elapsed * 0.45) * 20;
    const gy = -3.35;
    this.spot.position.set(gx, gy, gz);
    const radius = 3 + 2 * Math.sin(elapsed * 3);
    this.spot.scale.setScalar(radius);

    const sx = gx * 0.4;
    const sy = 26;
    const sz = gz + 18;
    this.beam.position.set(sx, sy, sz);
    this.dir.set(gx - sx, gy - sy, gz - sz);
    const len = this.dir.length();
    this.beam.scale.set(1, len, 1);
    this.mid.copy(this.dir).normalize();
    this.beam.quaternion.setFromUnitVectors(this.up, this.mid);

    const flicker = 0.85 + 0.15 * Math.sin(elapsed * 17);
    this.beamMat.opacity = energy * 0.28 * flicker;
    this.spotMat.opacity = energy * 0.7 * flicker;
  }

  reset(): void {
    this.beamMat.opacity = 0;
    this.spotMat.opacity = 0;
  }

  dispose(): void {
    this.beam.geometry.dispose();
    this.beamMat.dispose();
    this.spot.geometry.dispose();
    this.spotMat.dispose();
  }
}