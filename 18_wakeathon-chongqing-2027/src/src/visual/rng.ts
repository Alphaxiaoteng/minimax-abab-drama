/**
 * mulberry32 确定性伪随机：引擎内部所有「生成类」随机（粒子散布、爆型选色、
 * 楼群窗光）走同一个种子序列，保证同 dt + 同 apply 序列 ⇒ 同状态。
 * 注意：sample() 不读取本模块输出，判定与视觉生成彼此独立。
 */
export class Rng {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  range(min: number, max: number): number {
    return min + this.next() * (max - min);
  }

  int(maxExclusive: number): number {
    return Math.floor(this.next() * maxExclusive);
  }

  pick<T>(items: readonly T[]): T {
    return items[this.int(items.length)];
  }
}