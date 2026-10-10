/**
 * Fake 传输层：按 FakeTransportScript 注入故障，用于测试降级路径。
 * 一切输出由 MOCK_SEED + 调用序号派生，同调用序列 → 字节级一致。
 * 不真的 sleep：latencyMs 只在返回值里体现，避免拖慢测试。
 */

import { MOCK_SEED } from '../core/constants.js';
import { DeterministicRandom } from '../core/deterministic.js';
import { TransportError } from '../core/errors.js';
import type { FakeTransportScript, MiniMaxTransport, SpeechRequest, TextRequest } from '../core/types.js';

/** 确定性「伪上游」文本：模拟 live 成功时返回的回复（带情绪标记，供 client 解析） */
const CHAT_LINES: readonly string[] = [
  '证据不会说谎，尸温给出的时间比任何证词都诚实（语气：平静）',
  '把检材给我，别急着下结论，链条还差最后一环（语气：狐疑）',
  '我说了，证据链没闭死之前不讲假设，听懂了吗（语气：紧张）',
  '那一晚的监控回放我已经逐帧核对过，没有第二种可能（语气：悲恸）',
  '别用情绪覆盖事实，把时间线重新摆到我面前（语气：暴怒）',
];

export class FakeTransport implements MiniMaxTransport {
  readonly kind = 'fake' as const;

  readonly #chatFailures: number;
  readonly #speechFailures: number;
  readonly #latencyMs: number;
  #chatCalls = 0;
  #speechCalls = 0;

  constructor(script: FakeTransportScript = {}) {
    this.#chatFailures = script.chatFailures ?? 0;
    this.#speechFailures = script.speechFailures ?? 0;
    this.#latencyMs = script.latencyMs ?? 0;
  }

  /** 供测试断言「降级后不再触碰 transport」 */
  get chatCalls(): number {
    return this.#chatCalls;
  }

  get speechCalls(): number {
    return this.#speechCalls;
  }

  async chat(request: TextRequest): Promise<{ body: string; latencyMs: number }> {
    const seq = this.#chatCalls;
    this.#chatCalls += 1;
    if (seq < this.#chatFailures) {
      throw new TransportError('注入的文本通道故障');
    }
    const rng = DeterministicRandom.from(MOCK_SEED, seq);
    const content = rng.pick(CHAT_LINES);
    const payload = {
      created: 0,
      model: request.model,
      choices: [{ index: 0, message: { role: 'assistant', content } }],
    };
    return { body: JSON.stringify(payload), latencyMs: this.#latencyMs };
  }

  async speech(request: SpeechRequest): Promise<{ body: Uint8Array; latencyMs: number }> {
    const seq = this.#speechCalls;
    this.#speechCalls += 1;
    if (seq < this.#speechFailures) {
      throw new TransportError('注入的语音通道故障');
    }
    const rng = DeterministicRandom.from(MOCK_SEED, `speech:${seq}:${request.settings.voiceId}`);
    const bytes = Array.from({ length: 96 }, () => rng.nextInt(256));
    return { body: Uint8Array.from(bytes), latencyMs: this.#latencyMs };
  }
}
