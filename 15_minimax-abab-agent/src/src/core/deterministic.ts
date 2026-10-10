/**
 * 确定性伪随机数生成器与文本摘要工具。
 *
 * 契约（评测系统依赖，改动即破坏可复现性）：
 * 1. 同一 seed + 同一 step → 恒定输出，跨进程、跨平台一致。
 * 2. 不读取 Date/Math.random/环境变量。
 * 3. 整数运算全部落在 32 位无符号范围内，避免浮点漂移。
 */

/** 文本 → 32 位 FNV-1a 哈希，用于把任意字符串变成稳定 seed */
export function hashText(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

/**
 * mulberry32：单文件、无依赖、可复现的 PRNG。
 * 每次调用返回新的 next()，闭包内状态只增不改外部。
 */
export class DeterministicRandom {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  static from(seed: number, step: number | string): DeterministicRandom {
    const salt = typeof step === 'number' ? step : hashText(step);
    return new DeterministicRandom((seed ^ Math.imul(salt + 1, 0x9e3779b9)) >>> 0);
  }

  /** [0, 1) 均匀分布 */
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  }

  /** [0, maxExclusive) 整数 */
  nextInt(maxExclusive: number): number {
    return Math.floor(this.next() * maxExclusive);
  }

  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new RangeError('pick() 不能用于空数组');
    return items[this.nextInt(items.length)] as T;
  }

  /** Fisher–Yates，返回新数组，不修改入参 */
  shuffle<T>(items: readonly T[]): T[] {
    const out = [...items];
    for (let i = out.length - 1; i > 0; i -= 1) {
      const j = this.nextInt(i + 1);
      [out[i], out[j]] = [out[j] as T, out[i] as T];
    }
    return out;
  }
}

/** UTF-8 安全截断：按码点切割，绝不产生半个字符 */
export function truncate(text: string, maxChars: number): string {
  const codepoints = [...text];
  return codepoints.length <= maxChars ? text : `${codepoints.slice(0, maxChars).join('')}…`;
}

/** 把网络字节数格式化为人类可读体积，用于评测报告 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
