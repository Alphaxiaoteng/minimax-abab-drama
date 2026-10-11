/**
 * 多机位导播台控制面板
 * Camera Director Control Dock Component
 */
import React, { useState, useEffect } from 'react';
import type { CameraPresetName } from '../core/contract';
import { getCameraDirector } from '../camera/director';
import { bus } from '../core/events';

export const CameraDirectorDock: React.FC = () => {
  const [presets] = useState(() => 
    getCameraDirector().getListPresets()
  );
  const [currentPreset, setCurrentPreset] = useState<string>(() => 
    getCameraDirector().getCurrentPreset()
  );
  const [isTransitioning, setIsTransitioning] = useState(false);

  useEffect(() => {
    const handleCameraChange = (data: { preset: string; title: string; isTransitioning: boolean }) => {
      setCurrentPreset(data.preset);
      setIsTransitioning(data.isTransitioning);
    };

    bus.on('ui:cameraChange', handleCameraChange);
    return () => {
      bus.off('ui:cameraChange', handleCameraChange);
    };
  }, []);

  const handleSetPreset = (presetName: CameraPresetName) => {
    bus.emit('camera:change', { preset: presetName });
  };

  return (
    <div className="panel camera-dock" role="region" aria-label="机位导播台">
      <span className="panel-label">📹 机位导播台</span>
      <div className="chips dock-controls">
        {presets.map(preset => (
          <button
            key={preset.name}
            className={`chip ${currentPreset === preset.name ? 'active' : ''} ${isTransitioning && currentPreset !== preset.name ? 'disabled' : ''}`}
            onClick={() => handleSetPreset(preset.name)}
            disabled={isTransitioning && currentPreset !== preset.name}
            aria-label={`切换到${preset.title}`}>
            {preset.title}
          </button>
        ))}
      </div>
    </div>
  );
};
