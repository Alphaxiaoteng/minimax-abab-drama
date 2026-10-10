/**
 * MiniMaxClient：外呼的唯一编排点。
 * 降级与重试只在这里发生——传输层失败绝不上抛，永远兜底到确定性离线语料。
 * 一旦降级，mode 永久切为 'mock'，后续调用不再触碰网络。
 */

import type { AgentConfig } from '../core/config.js';
import type { MiniMaxClientLike, MiniMaxClientOptions } from '../core/contracts.js';
import { TEXT_LIMITS, VOICE_RANGES } from '../core/constants.js';
import { hashText } from '../core/deterministic.js';
import { TransportError, UpstreamError, ValidationError } from '../core/errors.js';
import type {
  ChatMessage,
  DegradationNotice,
  DegradationReason,
  Emotion,
  MiniMaxTransport,
  SpeechRequest,
  SpeechResult,
  TextRequest,
  TextResult,
  VoiceSettings,
} from '../core/types.js';
import { parseEmotion, stripEmotionMarkers } from './emotion-parser.js';
import { FakeTransport } from './fake-transport.js';
import { HttpTransport } from './http-transport.js';
import { estimateDurationMs, synthMockSpeech } from './mock-audio.js';
import { composeMockReply, personaFromSystemMessages } from './mock-corpus.js';

/** 把任意抛出物归一为降级原因 */
function degradationReasonFor(err: unknown): DegradationReason {
  return err instanceof TransportError ? 'transport_failure' : 'upstream_error';
}

/** 解析 chat 响应体；兼容 choices[0].message.content 与 choices[0].delta.content */
function parseChatContent(body: string): string | null {
  let json: unknown;
  try {
    json = JSON.parse(body);
  } catch {
    return null;
  }
  const choices = (json as { choices?: unknown } | null)?.choices;
  if (!Array.isArray(choices) || choices.length === 0) return null;
  const first = choices[0] as { message?: { content?: unknown }; delta?: { content?: unknown } };
  const content = first?.message?.content ?? first?.delta?.content;
  return typeof content === 'string' && content.length > 0 ? content : null;
}

export class MiniMaxClient implements MiniMaxClientLike {
  readonly #config: AgentConfig;
  readonly #transport: MiniMaxTransport;
  readonly #onDegrade: MiniMaxClientOptions['onDegrade'];
  readonly #notices: DegradationNotice[] = [];
  readonly #initialMode: 'live' | 'mock';
  #mode: 'live' | 'mock';
  #startupNoticeRecorded = false;
  /** 时间戳用调用计数代替 Date.now()，保证降级记录逐字节可复现 */
  #at = 0;

  constructor(options: MiniMaxClientOptions) {
    this.#config = options.config;
    this.#initialMode = options.config.mode;
    this.#mode = options.config.mode;
    this.#onDegrade = options.onDegrade;
    this.#transport = options.transport ?? (options.config.mode === 'live'
      ? new HttpTransport({
          baseUrl: options.config.baseUrl,
          apiKey: options.config.apiKey,
          requestTimeoutMs: options.config.requestTimeoutMs,
        })
      : new FakeTransport());
  }

  get mode(): 'live' | 'mock' {
    return this.#mode;
  }

  async chat(
    messages: readonly ChatMessage[],
    fallbackEmotion: Emotion = 'calm',
  ): Promise<TextResult> {
    this.#maybeRecordStartupNotice();
    if (this.#mode === 'mock') {
      return this.#mockChat(messages, fallbackEmotion);
    }

    const request: TextRequest = {
      messages,
      model: this.#config.textModel,
      temperature: TEXT_LIMITS.temperature,
      maxTokens: TEXT_LIMITS.maxTokens,
    };
    const attempts = this.#config.maxRetries + 1;
    let lastError: unknown = null;

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const { body, latencyMs } = await this.#transport.chat(request, new AbortController().signal);
        const content = parseChatContent(body);
        if (content === null) {
          this.#degrade('upstream_error', '上游响应无法解析为 choices[0].message/delta.content');
          return this.#mockChat(messages, fallbackEmotion);
        }
        return {
          text: content,
          emotion: parseEmotion(content, fallbackEmotion),
          source: 'live',
          latencyMs,
        };
      } catch (err) {
        if (err instanceof UpstreamError) {
          this.#degrade('upstream_error', err.message);
          return this.#mockChat(messages, fallbackEmotion);
        }
        lastError = err;
      }
    }

    const message = lastError instanceof Error ? lastError.message : String(lastError ?? '未知故障');
    this.#degrade(degradationReasonFor(lastError), message);
    return this.#mockChat(messages, fallbackEmotion);
  }

  async speech(
    text: string,
    settings: VoiceSettings,
    fallbackEmotion?: Emotion,
  ): Promise<SpeechResult> {
    this.#assertVoiceSettings(settings);
    this.#maybeRecordStartupNotice();

    const cleanText = stripEmotionMarkers(text);
    const emotion = settings.emotion ?? fallbackEmotion ?? 'calm';
    const effectiveSettings: VoiceSettings = { ...settings, emotion };
    const durationMs = estimateDurationMs(cleanText, effectiveSettings.speed);

    if (this.#mode === 'mock') {
      return this.#mockSpeech(cleanText, effectiveSettings, durationMs);
    }

    const request: SpeechRequest = {
      text: cleanText,
      model: this.#config.speechModel,
      settings: effectiveSettings,
    };
    const attempts = this.#config.maxRetries + 1;
    let lastError: unknown = null;

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const { body, latencyMs } = await this.#transport.speech(request, new AbortController().signal);
        return {
          audio: body,
          mimeType: 'audio/mpeg',
          durationMs,
          settings: effectiveSettings,
          source: 'live',
          latencyMs,
        };
      } catch (err) {
        if (err instanceof UpstreamError) {
          this.#degrade('upstream_error', err.message);
          return this.#mockSpeech(cleanText, effectiveSettings, durationMs);
        }
        lastError = err;
      }
    }

    const message = lastError instanceof Error ? lastError.message : String(lastError ?? '未知故障');
    this.#degrade(degradationReasonFor(lastError), message);
    return this.#mockSpeech(cleanText, effectiveSettings, durationMs);
  }

  degradations(): readonly { reason: string; message: string; at: number }[] {
    return [...this.#notices];
  }

  /** 离线语料回复：由 messages 指纹 + userText + turnIndex 派生，幂等 */
  #mockChat(messages: readonly ChatMessage[], fallbackEmotion: Emotion): TextResult {
    const persona = personaFromSystemMessages(messages);
    let turnIndex = 0;
    let userText = '';
    for (const m of messages) {
      if (m.role === 'user') {
        turnIndex += 1;
        userText = m.content;
      }
    }
    const messageFingerprint = hashText(
      messages.map((m) => `${m.role}\u0000${m.content}`).join('\u0001'),
    );
    const text = composeMockReply({
      persona,
      emotion: fallbackEmotion,
      userText,
      turnIndex,
      messageFingerprint,
    });
    return {
      text,
      emotion: parseEmotion(text, fallbackEmotion),
      source: 'mock',
      latencyMs: 0,
    };
  }

  #mockSpeech(
    cleanText: string,
    settings: VoiceSettings,
    durationMs: number,
  ): SpeechResult {
    return {
      audio: synthMockSpeech(cleanText, settings, durationMs),
      mimeType: 'audio/wav',
      durationMs,
      settings,
      source: 'mock',
      latencyMs: 0,
    };
  }

  /** mock 模式 + 空凭证 = 离线降级，只在首次调用记一次 notice */
  #maybeRecordStartupNotice(): void {
    if (this.#startupNoticeRecorded || this.#initialMode !== 'mock') return;
    this.#startupNoticeRecorded = true;
    const reason: DegradationReason = this.#config.apiKey.length === 0 ? 'no_credential' : 'forced_offline';
    this.#recordNotice(reason, '已切换离线确定性语料');
  }

  #degrade(reason: DegradationReason, message: string): void {
    this.#mode = 'mock';
    this.#recordNotice(reason, message);
  }

  #recordNotice(reason: DegradationReason, message: string): void {
    const notice: DegradationNotice = { reason, message, at: this.#at };
    this.#at += 1;
    this.#notices.push(notice);
    this.#onDegrade?.({ reason, message, at: notice.at });
  }

  #assertVoiceSettings(settings: VoiceSettings): void {
    if (typeof settings.voiceId !== 'string' || settings.voiceId.trim().length === 0) {
      throw new ValidationError('voiceId 不能为空');
    }
    this.#assertRange('speed', settings.speed, VOICE_RANGES.speed);
    this.#assertRange('vol', settings.vol, VOICE_RANGES.vol);
    this.#assertRange('pitch', settings.pitch, VOICE_RANGES.pitch);
  }

  #assertRange(name: string, value: number, range: readonly [number, number]): void {
    const [min, max] = range;
    if (!Number.isFinite(value) || value < min || value > max) {
      throw new ValidationError(`参数 ${name} 越界：${value}，合法区间 [${min}, ${max}]`);
    }
  }
}