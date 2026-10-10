/**
 * HTTP 传输层：真实 HTTPS 调用 MiniMax 开放平台（abab 文本 + T2A v2 语音）。
 * 只做「把请求变成字节」这一件事；降级与重试属于 MiniMaxClient 的职责边界。
 */

import { MINIMAX_DEFAULTS } from '../core/constants.js';
import { TransportError, UpstreamError, ValidationError } from '../core/errors.js';
import type { MiniMaxTransport, SpeechRequest, TextRequest } from '../core/types.js';

export interface HttpTransportOptions {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly requestTimeoutMs: number;
  /** 注入时钟，仅用于统计延迟；缺省回落 Date.now */
  readonly now?: () => number;
}

/** 把 `data.audio` 的 hex 字符串解码成字节 */
function decodeHexAudio(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new UpstreamError('TTS 响应音频 hex 长度非法');
  }
  if (!/^[0-9a-fA-F]*$/.test(hex)) {
    throw new UpstreamError('TTS 响应音频 hex 含非法字符');
  }
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    const byte = Number.parseInt(hex.slice(i, i + 2), 16);
    if (Number.isNaN(byte)) {
      throw new UpstreamError('TTS 响应音频 hex 含非法字符');
    }
    bytes[i / 2] = byte;
  }
  return bytes;
}

/** 把 fetch 层的各种异常归一为 TransportError / UpstreamError */
function normalizeFetchError(err: unknown, timeoutMs: number, timeoutSignal: AbortSignal): never {
  const timedOut =
    timeoutSignal.aborted ||
    (err instanceof DOMException && (err.name === 'TimeoutError' || err.name === 'AbortError'));
  if (timedOut) {
    throw new TransportError(`请求超时（${timeoutMs}ms）`, { cause: err });
  }
  const message = err instanceof Error ? err.message : String(err);
  throw new TransportError(`网络请求失败：${message}`, { cause: err });
}

export class HttpTransport implements MiniMaxTransport {
  readonly kind = 'http' as const;

  readonly #baseUrl: string;
  readonly #apiKey: string;
  readonly #timeoutMs: number;
  readonly #now: () => number;

  constructor(options: HttpTransportOptions) {
    this.#baseUrl = options.baseUrl.trim().replace(/\/+$/, '');
    this.#apiKey = options.apiKey;
    this.#timeoutMs = options.requestTimeoutMs;
    this.#now = options.now ?? (() => Date.now());
  }

  async chat(request: TextRequest, signal: AbortSignal): Promise<{ body: string; latencyMs: number }> {
    const payload = {
      model: request.model,
      messages: request.messages,
      temperature: request.temperature,
      max_tokens: request.maxTokens,
      stream: false,
    };
    const started = this.#now();
    const res = await this.#post(`${this.#baseUrl}${MINIMAX_DEFAULTS.textPath}`, payload, signal);
    let body: string;
    try {
      body = await res.text();
    } catch (err) {
      throw new TransportError(`读取响应文本失败：${err instanceof Error ? err.message : String(err)}`, {
        cause: err,
      });
    }
    return { body, latencyMs: this.#now() - started };
  }

  async speech(request: SpeechRequest, signal: AbortSignal): Promise<{ body: Uint8Array; latencyMs: number }> {
    const s = request.settings;
    const payload = {
      model: request.model,
      text: request.text,
      stream: false,
      voice_setting: {
        voice_id: s.voiceId,
        speed: s.speed,
        vol: s.vol,
        pitch: s.pitch,
        emotion: s.emotion,
      },
      audio_setting: {
        sample_rate: 32000,
        bitrate: 128000,
        format: 'mp3',
        channel: 1,
      },
    };
    const started = this.#now();
    const res = await this.#post(`${this.#baseUrl}${MINIMAX_DEFAULTS.ttsPath}`, payload, signal);

    const contentType = res.headers.get('content-type') ?? '';
    if (!contentType.includes('json')) {
      // 上游直接回二进制音频：原样透传字节
      const buf = await res.arrayBuffer();
      return { body: new Uint8Array(buf), latencyMs: this.#now() - started };
    }

    let parsed: unknown;
    try {
      parsed = await res.json();
    } catch (err) {
      throw new UpstreamError(`TTS 响应 JSON 解析失败：${err instanceof Error ? err.message : String(err)}`);
    }
    const audio = (parsed as { data?: { audio?: unknown } } | null)?.data?.audio;
    if (typeof audio !== 'string' || audio.length === 0) {
      throw new UpstreamError('TTS 响应缺少 data.audio 字段');
    }
    const body = decodeHexAudio(audio);
    return { body, latencyMs: this.#now() - started };
  }

  #post(url: string, payload: unknown, signal: AbortSignal): Promise<Response> {
    if (this.#apiKey.length === 0) {
      throw new ValidationError('缺少 API Key，无法发起真实请求');
    }
    const timeoutSignal = AbortSignal.timeout(this.#timeoutMs);
    const combined = AbortSignal.any([signal, timeoutSignal]);
    return fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.#apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: combined,
    }).then(
      (res) => {
        if (!res.ok) {
          throw new UpstreamError(`上游返回 HTTP ${res.status}`, res.status);
        }
        return res;
      },
      (err: unknown) => normalizeFetchError(err, this.#timeoutMs, timeoutSignal),
    );
  }
}
