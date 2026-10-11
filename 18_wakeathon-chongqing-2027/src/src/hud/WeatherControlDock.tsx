/**
 * 赛博微气候控制面板
 * Cyber Weather Control Panel Component
 */
import React from 'react';
import { bus } from '../core/events';

export interface WeatherControlProps {
  fogDensity: number;
  volumetricLight: number;
  bloomIntensity: number;
}

export const WeatherControlDock: React.FC<{
  controls?: WeatherControlProps;
  onFogChange?: (v: number) => void;
  onLightChange?: (v: number) => void;
  onBloomChange?: (v: number) => void;
}> = ({ 
  controls = { fogDensity: 0.5, volumetricLight: 0.7, bloomIntensity: 0.9 },
  onFogChange,
  onLightChange,
  onBloomChange 
}) => {
  const handleFireworksTrigger = () => {
    bus.emit('weather:fireworks', {});
    bus.emit('agent:command', { action: 'fireworks', intensity: 1 });
  };

  return (
    <div className="panel weather-dock" role="region" aria-label="微气候控制面板">
      <span className="panel-label">🌫️ 微气候控制</span>
      <div className="weather-sliders">
        <div className="slider-group">
          <label htmlFor="fog-density">大雾浓度 Fog Density</label>
          <input
            type="range"
            id="fog-density"
            min="0"
            max="1"
            step="0.01"
            value={controls?.fogDensity ?? 0.5}
            onChange={(e) => {
              const value = parseFloat(e.target.value);
              bus.emit('weather:fogDensity', { value });
              onFogChange?.(value);
            }}
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={controls?.fogDensity ?? 0.5}
          />
        </div>
        <div className="slider-group">
          <label htmlFor="volumetric-light">体积光强 Volumetric Light</label>
          <input
            type="range"
            id="volumetric-light"
            min="0"
            max="1"
            step="0.01"
            value={controls?.volumetricLight ?? 0.7}
            onChange={(e) => {
              const value = parseFloat(e.target.value);
              bus.emit('weather:volumetricLight', { value });
              onLightChange?.(value);
            }}
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={controls?.volumetricLight ?? 0.7}
          />
        </div>
        <div className="slider-group">
          <label htmlFor="bloom-intensity">霓虹泛光辉光 Bloom Intensity</label>
          <input
            type="range"
            id="bloom-intensity"
            min="0"
            max="1"
            step="0.01"
            value={controls?.bloomIntensity ?? 0.9}
            onChange={(e) => {
              const value = parseFloat(e.target.value);
              bus.emit('weather:bloom', { value });
              onBloomChange?.(value);
            }}
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={controls?.bloomIntensity ?? 0.9}
          />
        </div>
      </div>
      <button 
        className="chip weather-trigger"
        onClick={handleFireworksTrigger}
        aria-label="触发跨江烟花">
        🎆 跨江烟花 Fireworks
      </button>
    </div>
  );
};
