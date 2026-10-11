import { describe, it, expect } from 'vitest';
import { InterrogationPsychologyEngine } from './psychology';
import { WavPcmSynthesizer } from './audio_synth';

describe('psychology and audio synthesis suite', () => {
  it('InterrogationPsychologyEngine: 初始状态平静，心率计算符合生理学', () => {
    const engine = new InterrogationPsychologyEngine(10, 30);
    expect(engine.getState()).toBe('CALM');
    expect(engine.getHeartRate()).toBeGreaterThan(70);
    expect(engine.getHeartRate()).toBeLessThan(90);
  });

  it('InterrogationPsychologyEngine: 战术循环引发心理崩溃与核心口供解锁', () => {
    // 初始防备 80, 紧张 30
    const engine = new InterrogationPsychologyEngine(30, 80);

    // 1. 共情瓦解防卫
    const fb1 = engine.applyTactic('EMPATHY');
    expect(fb1.defensiveness).toBeLessThan(80);

    // 2. 连续共情与施压
    engine.applyTactic('EMPATHY');
    engine.applyTactic('PRESSURE');
    engine.applyTactic('PRESSURE');

    // 3. 铁证突袭，引爆心防 (Breakdown)
    const fbFinal = engine.applyTactic('EVIDENCE_SLAM', 1.0);
    expect(fbFinal.currentState).toBe('BREAKDOWN');
    expect(fbFinal.heartRateBpm).toBeGreaterThan(130);
    expect(fbFinal.unlockedTestimony).toContain('绝密口供');
  });

  it('WavPcmSynthesizer: 生成有效标准 RIFF/WAVE 文件头与 Base64 格式', () => {
    const dataUri = WavPcmSynthesizer.synthesizeToneBase64(440, 0.2, 22050);
    expect(dataUri).toMatch(/^data:audio\/wav;base64,/);

    const base64Str = dataUri.replace('data:audio/wav;base64,', '');
    const buf = Buffer.from(base64Str, 'base64');

    expect(buf.toString('ascii', 0, 4)).toBe('RIFF');
    expect(buf.toString('ascii', 8, 12)).toBe('WAVE');
    expect(buf.toString('ascii', 12, 16)).toBe('fmt ');
    expect(buf.readUInt16LE(20)).toBe(1); // PCM 格式
    expect(buf.readUInt16LE(22)).toBe(1); // 单声道
    expect(buf.readUInt32LE(24)).toBe(22050); // 采样率
    expect(buf.toString('ascii', 36, 40)).toBe('data');
    expect(buf.length).toBeGreaterThan(44);
  });
});
