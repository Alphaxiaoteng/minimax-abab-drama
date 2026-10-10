/**
 * 确定性 WAV 合成器：离线降级时生成真实可播放的 PCM 音频。
 * 派生键 = MOCK_SEED ^ hashText(voiceId) ^ hashText(emotion) ^ hashText(text)，
 * 因此「同文本同音色同情绪 → 字节级同波形；不同 voiceId / 不同情绪 → 不同波形」。
 */

import { MOCK_SEED } from '../core/constants.js';
import { DeterministicRandom, hashText } from '../core/deterministic.js';
import { ValidationError } from '../core/errors.js';
import { EMOTION_LABELS } from '../core/types.js';
import type { Emotion, VoiceSettings } from '../core/types.js';

/** 采样率固定 16kHz、16bit、单声道 → 每毫秒 32 字节 */
const SAMPLE_RATE = 16_000;
const BYTES_PER_MS = (SAMPLE_RATE / 1000) * 2;

/** 情绪 → 谐波比例 / 颤音频率 / 音节抖动，保证不同情绪可听辨 */
const EMOTION_AUDIO_PROFILE: Readonly<
  Record<Emotion, { harmonic: number; vibrato: number; jitter: number }>
> = {
  calm: { harmonic: 0.18, vibrato: 4.5, jitter: 0.004 },
  joyful: { harmonic: 0.32, vibrato: 6.5, jitter: 0.008 },
  tense: { harmonic: 0.24, vibrato: 8.0, jitter: 0.02 },
  sorrowful: { harmonic: 0.12, vibrato: 3.5, jitter: 0.006 },
  furious: { harmonic: 0.42, vibrato: 7.5, jitter: 0.014 },
  fearful: { harmonic: 0.28, vibrato: 9.5, jitter: 0.024 },
  suspicious: { harmonic: 0.22, vibrato: 5.5, jitter: 0.01 },
  tender: { harmonic: 0.15, vibrato: 5.0, jitter: 0.005 },
};

/** 按每汉字 ~180ms / speed 估算时长，下限 300ms */
export function estimateDurationMs(text: string, speed: number): number {
  const chars = [...text].length;
  return Math.max(300, Math.round((chars * 180) / speed));
}

/** 写入小端 16bit PCM 样本 */
function putSample(view: DataView, byteOffset: number, sample: number): void {
  const clamped = Math.max(-32768, Math.min(32767, Math.round(sample)));
  view.setInt16(byteOffset, clamped, true);
}

function writeWavHeader(view: DataView, dataBytes: number): void {
  view.setUint32(0, 0x46464952, false); // 'RIFF'
  view.setUint32(4, 36 + dataBytes, true);
  view.setUint32(8, 0x45564157, false); // 'WAVE'
  view.setUint32(12, 0x20746d66, false); // 'fmt '
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // 单声道
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true); // byteRate
  view.setUint16(32, 2, true); // blockAlign
  view.setUint16(34, 16, true); // bitsPerSample
  view.setUint32(36, 0x61746164, false); // 'data'
  view.setUint32(40, dataBytes, true);
}

/** 解析 WAV 头（校验 RIFF/WAVE 与 fmt/data 块），供测试与评测锚定 */
export function parseWavHeader(bytes: Uint8Array): {
  sampleRate: number;
  channels: number;
  bitsPerSample: number;
  dataBytes: number;
} {
  if (bytes.length < 44) {
    throw new ValidationError('WAV 字节长度不足 44 字节，非法头');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (offset: number, expect: number): void => {
    if (view.getUint32(offset, false) !== expect) {
      throw new ValidationError(`WAV 头在偏移 ${offset} 处校验失败`);
    }
  };
  tag(0, 0x46464952); // RIFF
  tag(8, 0x45564157); // WAVE
  tag(12, 0x20746d66); // fmt
  tag(36, 0x61746164); // data
  return {
    sampleRate: view.getUint32(24, true),
    channels: view.getUint16(22, true),
    bitsPerSample: view.getUint16(34, true),
    dataBytes: view.getUint32(40, true),
  };
}

/**
 * 合成确定性 WAV：44 字节标准头 + PCM 数据。
 * 不变式：audio.byteLength === 44 + durationMs * 32。
 */
export function synthMockSpeech(text: string, settings: VoiceSettings, durationMs: number): Uint8Array {
  if (!Number.isInteger(durationMs) || durationMs < 0) {
    throw new ValidationError(`durationMs 必须是非负整数，收到 ${durationMs}`);
  }
  const dataBytes = durationMs * BYTES_PER_MS;
  const total = 44 + dataBytes;
  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  writeWavHeader(view, dataBytes);

  const emotion = settings.emotion;
  const profile = EMOTION_AUDIO_PROFILE[emotion];
  const rng = DeterministicRandom.from(
    MOCK_SEED ^ hashText(settings.voiceId) ^ hashText(emotion),
    hashText(text),
  );

  // 基频 90–320Hz，由 voiceId 决定；pitch 做半音偏移；vol 映射振幅
  const baseFreq = 90 + (hashText(settings.voiceId) % 231);
  const freq0 = baseFreq * Math.pow(2, settings.pitch / 12);
  const amplitude = 32767 * 0.85 * (settings.vol / 10);
  const chars = [...text];
  const syllableCount = Math.max(1, chars.length);
  const samplesPerSyllable = durationMs === 0 ? 0 : Math.ceil((durationMs * 16) / syllableCount);
  let sampleIndex = 0;
  const totalSamples = dataBytes / 2;

  while (sampleIndex < totalSamples) {
    const syllableFreq = freq0 * (1 + (rng.next() - 0.5) * 2 * profile.jitter);
    const span = Math.min(samplesPerSyllable, totalSamples - sampleIndex);
    const phase = rng.next() * Math.PI * 2;
    for (let n = 0; n < span; n += 1) {
      const t = n / SAMPLE_RATE;
      const envelope = Math.min(1, n / 320) * Math.min(1, (span - n) / 320);
      const vibrato = 1 + 0.015 * Math.sin(2 * Math.PI * profile.vibrato * t);
      const w = 2 * Math.PI * syllableFreq * vibrato * t + phase;
      const raw = Math.sin(w) + profile.harmonic * Math.sin(2 * w) + (profile.harmonic / 2) * Math.sin(3 * w);
      putSample(view, 44 + (sampleIndex + n) * 2, raw * envelope * amplitude);
    }
    sampleIndex += span;
  }
  return bytes;
}
