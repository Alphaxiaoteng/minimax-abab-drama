import * as THREE from "three";
import type { CameraPresetName } from "../core/contract";
export type { CameraPresetName };

export interface CameraPreset {
  name: CameraPresetName;
  title: string;
  position: { x: number; y: number; z: number };
  lookAt: { x: number; y: number; z: number };
  fov?: number;
  duration?: number;
}

export const CAMERA_PRESETS: ReadonlyArray<CameraPreset> = Object.freeze([
  { name: 'jie-fang-bei-aerial', title: '解放碑高空俯瞰', position: { x: 30, y: 40, z: -20 }, lookAt: { x: 0, y: 12, z: -10 }, fov: 65, duration: 1500 },
  { name: 'hong-ya-dong-closeup', title: '洪崖洞吊脚楼近景穿梭', position: { x: 18, y: 8, z: 28 }, lookAt: { x: 14, y: 4, z: 22 }, fov: 52, duration: 1200 },
  { name: 'nan-shan-panorama', title: '南山一棵树全景夜巡', position: { x: -50, y: 35, z: 70 }, lookAt: { x: 0, y: 10, z: -20 }, fov: 70, duration: 1800 },
  { name: 'cable-car-pov', title: '长江索道第一视角', position: { x: 35, y: 15, z: 5 }, lookAt: { x: -30, y: 12, z: -35 }, fov: 58, duration: 1400 },
  { name: 'rail-transit-tracking', title: '轻轨穿楼动态追踪', position: { x: 25, y: 10, z: -25 }, lookAt: { x: 8, y: 6, z: -8 }, fov: 55, duration: 1600 },
] as const);

export interface CameraTransition {
  startTime: number;
  duration: number;
  fromFOV: number;
  toFOV: number;
  fromPosition: THREE.Vector3;
  toPosition: THREE.Vector3;
  fromLookAt: THREE.Vector3;
  toLookAt: THREE.Vector3;
  currentPresetName: CameraPresetName;
}
