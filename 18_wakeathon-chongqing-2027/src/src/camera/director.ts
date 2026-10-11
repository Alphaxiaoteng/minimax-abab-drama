/**
 * 电影级相机导播控制逻辑
 * Cinematic Camera Director Implementation
 */
import { CAMERA_PRESETS, type CameraPresetName } from './types';
import { bus } from '../core/events';

export interface CameraDirectorOptions {}

export class CameraDirector {
  private currentPreset: CameraPresetName;
  private isTransitioning = false;
  private transitionStartTime = 0;
  private transitionDuration = 0;
  private fromFOV: number;
  private toFOV: number;
  private fromPosition: { x: number; y: number; z: number };
  private toPosition: { x: number; y: number; z: number };
  private fromLookAt: { x: number; y: number; z: number };
  private toLookAt: { x: number; y: number; z: number };

  constructor() {
    this.currentPreset = 'jie-fang-bei-aerial'; // Default preset
    this.isTransitioning = false;
    this.fromFOV = 58;
    this.toFOV = 58;
    this.fromPosition = { x: 0, y: 13, z: 58 };
    this.toPosition = { x: 0, y: 13, z: 58 };
    this.fromLookAt = { x: 0, y: 9, z: -20 };
    this.toLookAt = { x: 0, y: 9, z: -20 };
    
    // Listen for camera change commands from the scene engine
    bus.on('camera:change', (data: { preset: CameraPresetName }) => {
      this.setActivePreset(data.preset);
    });
  }

  /** 获取所有预设列表 */
  getListPresets(): Array<{ name: CameraPresetName; title: string }> {
    return CAMERA_PRESETS.map(p => ({ name: p.name, title: p.title }));
  }

  /** 获取当前预设名称 */
  getCurrentPreset(): CameraPresetName {
    return this.currentPreset;
  }

  /** 是否正在过渡 */
  isCurrentlyTransitioning(): boolean {
    return this.isTransitioning;
  }

  /** 设置激活的机位预设（平滑过渡） */
  async setActivePreset(presetName: CameraPresetName): Promise<void> {
    if (this.isTransitioning) {
      console.warn(`Camera transition already in progress`);
      return;
    }

    const targetPreset = CAMERA_PRESETS.find(p => p.name === presetName);
    if (!targetPreset) {
      console.error(`Unknown camera preset: ${presetName}`);
      return;
    }

    // 记录当前状态为"from"状态
    this.fromFOV = this.toFOV;
    this.fromPosition = { ...this.toPosition };
    this.fromLookAt = { ...this.toLookAt };

    // 设置目标状态
    this.toFOV = targetPreset.fov ?? 58;
    this.toPosition = targetPreset.position;
    this.toLookAt = targetPreset.lookAt;
    this.transitionDuration = targetPreset.duration ?? 1500;
    this.transitionStartTime = performance.now();
    this.isTransitioning = true;

    // Emit event for UI update
    bus.emit('ui:cameraChange', {
      preset: presetName,
      title: targetPreset.title,
      isTransitioning: true,
    });

    // Schedule completion check
    setTimeout(() => {
      this.isTransitioning = false;
      this.currentPreset = presetName;
      bus.emit('ui:cameraChange', {
        preset: presetName,
        title: targetPreset.title,
        isTransitioning: false,
      });
    }, this.transitionDuration);
  }

  /** 计算当前的插值参数（供渲染引擎调用） */
  getCurrentInterpolation(time: number): {
    fov: number;
    position: { x: number; y: number; z: number };
    lookAt: { x: number; y: number; z: number };
    progress: number;
  } {
    if (!this.isTransitioning) {
      // Return final preset values
      const preset = CAMERA_PRESETS.find(p => p.name === this.currentPreset);
      if (!preset) {
        return {
          fov: this.toFOV,
          position: this.toPosition,
          lookAt: this.toLookAt,
          progress: 1,
        };
      }
      return {
        fov: preset.fov ?? 58,
        position: preset.position,
        lookAt: preset.lookAt,
        progress: 1,
      };
    }

    const elapsed = time - this.transitionStartTime;
    const progress = Math.min(1, elapsed / this.transitionDuration);

    // Ease-out cubic function for smooth transitions
    const easedProgress = 1 - Math.pow(1 - progress, 3);

    return {
      fov: this.fromFOV + (this.toFOV - this.fromFOV) * easedProgress,
      position: {
        x: this.fromPosition.x + (this.toPosition.x - this.fromPosition.x) * easedProgress,
        y: this.fromPosition.y + (this.toPosition.y - this.fromPosition.y) * easedProgress,
        z: this.fromPosition.z + (this.toPosition.z - this.fromPosition.z) * easedProgress,
      },
      lookAt: {
        x: this.fromLookAt.x + (this.toLookAt.x - this.fromLookAt.x) * easedProgress,
        y: this.fromLookAt.y + (this.toLookAt.y - this.fromLookAt.y) * easedProgress,
        z: this.fromLookAt.z + (this.toLookAt.z - this.fromLookAt.z) * easedProgress,
      },
      progress: easedProgress,
    };
  }

  /** 重置到默认预设 */
  resetToDefault(): void {
    this.setActivePreset('jie-fang-bei-aerial');
  }
}

// Export singleton instance for easy access
let cameraDirectorInstance: CameraDirector | null = null;

export function getCameraDirector(_opts?: CameraDirectorOptions): CameraDirector {
  if (!cameraDirectorInstance) {
    cameraDirectorInstance = new CameraDirector();
  }
  return cameraDirectorInstance;
}

export function resetCameraDirector(): void {
  cameraDirectorInstance = null;
}
