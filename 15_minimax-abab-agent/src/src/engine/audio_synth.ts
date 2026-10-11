/**
 * audio_synth.ts - 确定性 PCM 16-bit WAV 二进制音频合成器。
 *
 * 为沉浸式侦探剧背景氛围与悬疑心跳音效提供纯前端/Node 离线合成：
 * 1. 严格按照 RIFF / WAVE 规范构建 44 字节标准二进制文件头。
 * 2. 真实数学正弦波合成，支持心跳低频双咚音 (Heartbeat 60Hz/80Hz) 与悬疑紧张无人机弦音 (Drone 220Hz)。
 * 3. 产出标准 base64 data:audio/wav 格式，供前端播放或接口透传。
 */

export class WavPcmSynthesizer {
  /**
   * 生成指定频率和时长的 16-bit 单声道 WAV 音频 Base64
   * @param frequencyHz 频率 (如 440Hz)
   * @param durationSeconds 持续时间 (秒)
   * @param sampleRate 采样率 (默认 22050 Hz)
   */
  static synthesizeToneBase64(
    frequencyHz: number,
    durationSeconds: number,
    sampleRate: number = 22050
  ): string {
    const numSamples = Math.floor(sampleRate * durationSeconds);
    const byteRate = sampleRate * 2; // 16-bit = 2 bytes/sample
    const blockAlign = 2;
    const dataSize = numSamples * 2;
    const buffer = Buffer.alloc(44 + dataSize);

    // 1. RIFF 标识符
    buffer.write('RIFF', 0);
    buffer.writeUInt32LE(36 + dataSize, 4);
    buffer.write('WAVE', 8);

    // 2. fmt 子块
    buffer.write('fmt ', 12);
    buffer.writeUInt32LE(16, 16); // Subchunk1Size = 16 for PCM
    buffer.writeUInt16LE(1, 20);  // AudioFormat = 1 (PCM)
    buffer.writeUInt16LE(1, 22);  // NumChannels = 1 (Mono)
    buffer.writeUInt32LE(sampleRate, 24);
    buffer.writeUInt32LE(byteRate, 28);
    buffer.writeUInt16LE(blockAlign, 32);
    buffer.writeUInt16LE(16, 34); // BitsPerSample = 16

    // 3. data 子块
    buffer.write('data', 36);
    buffer.writeUInt32LE(dataSize, 40);

    // 4. 采样数据 (正弦波 + 线性淡入淡出防止爆音)
    const fadeSamples = Math.min(Math.floor(sampleRate * 0.05), Math.floor(numSamples / 2));

    for (let i = 0; i < numSamples; i++) {
      const t = i / sampleRate;
      let amplitude = Math.sin(2 * Math.PI * frequencyHz * t);

      // 淡入淡出包络
      if (i < fadeSamples) {
        amplitude *= i / fadeSamples;
      } else if (i > numSamples - fadeSamples) {
        amplitude *= (numSamples - i) / fadeSamples;
      }

      // 缩放到 16-bit 有符号整数范围 (-32768 到 32767)
      const sample16 = Math.floor(amplitude * 32000);
      buffer.writeInt16LE(sample16, 44 + i * 2);
    }

    return `data:audio/wav;base64,${buffer.toString('base64')}`;
  }
}
