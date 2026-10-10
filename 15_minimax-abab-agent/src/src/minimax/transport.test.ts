/**
 * 传输层测试：fake 的确定性、http 的 hex 解码与错误归一（mock fetch，不触网）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SpeechRequest, TextRequest } from '../core/types.js';
import { TransportError, UpstreamError, ValidationError } from '../core/errors.js';
import { FakeTransport } from './fake-transport.js';
import { HttpTransport } from './http-transport.js';
import { estimateDurationMs, parseWavHeader, synthMockSpeech } from './mock-audio.js';
import { classifyIntent, composeMockReply, personaFromSystemMessages } from './mock-corpus.js';

const textRequest = (content: string): TextRequest => ({
  messages: [{ role: 'user', content }],
  model: 'abab7-chat-preview',
  temperature: 0.9,
  maxTokens: 1024,
});

const speechRequest = (text: string): SpeechRequest => ({
  text,
  model: 'speech-02-hd',
  settings: { voiceId: 'female-shaonv', speed: 1.0, vol: 5.0, pitch: 0, emotion: 'calm' },
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FakeTransport：确定性 + 故障注入', () => {
  it('同调用序列 → 字节级一致', async () => {
    const a = new FakeTransport();
    const b = new FakeTransport();
    const resA = await a.chat(textRequest('证据呢'));
    const resB = await b.chat(textRequest('证据呢'));
    expect(resA.body).toBe(resB.body);
    expect(resA.latencyMs).toBe(0);
  });

  it('前 chatFailures 次抛 TransportError，之后成功', async () => {
    const fake = new FakeTransport({ chatFailures: 3 });
    for (let i = 0; i < 3; i += 1) {
      await expect(fake.chat(textRequest('x'))).rejects.toBeInstanceOf(TransportError);
    }
    const ok = await fake.chat(textRequest('x'));
    expect(ok.body).toContain('choices');
    expect(fake.chatCalls).toBe(4);
  });

  it('speechFailures 同理', async () => {
    const fake = new FakeTransport({ speechFailures: 2 });
    await expect(fake.speech(speechRequest('你好'))).rejects.toBeInstanceOf(TransportError);
    await expect(fake.speech(speechRequest('你好'))).rejects.toBeInstanceOf(TransportError);
    const ok = await fake.speech(speechRequest('你好'));
    expect(ok.body.byteLength).toBe(96);
    expect(fake.speechCalls).toBe(3);
  });

  it('latencyMs 脚本值透传到返回值但不真的 sleep', async () => {
    const fake = new FakeTransport({ latencyMs: 37 });
    const started = Date.now();
    const res = await fake.chat(textRequest('x'));
    expect(res.latencyMs).toBe(37);
    expect(Date.now() - started).toBeLessThan(30);
  });

  it('确定性跨新建实例一致（speech 字节相同）', async () => {
    const r1 = await new FakeTransport().speech(speechRequest('同文本'));
    const r2 = await new FakeTransport().speech(speechRequest('同文本'));
    expect(r1.body).toEqual(r2.body);
  });
});

describe('HttpTransport：hex 解码 / 错误归一 / 超时', () => {
  const opts = { baseUrl: 'https://api.minimax.chat', apiKey: 'k', requestTimeoutMs: 1000 };

  it('chat 返回原始文本并 POST 正确 URL 与头部', async () => {
    const fetchMock = vi.fn(async () => new Response('{"choices":[]}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const http = new HttpTransport(opts);
    const res = await http.chat(textRequest('x'), new AbortController().signal);
    expect(res.body).toBe('{"choices":[]}');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://api.minimax.chat/v1/text/chatcompletion_v2');
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer k');
    expect(headers['Content-Type']).toBe('application/json');
    const payload = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(payload.stream).toBe(false);
    expect(payload.max_tokens).toBe(1024);
  });

  it('speech 把 data.audio 的 hex 解码成字节', async () => {
    const hex = '48656c6c6f';
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ data: { audio: hex } }), {
        headers: { 'content-type': 'application/json' },
      })),
    );
    const http = new HttpTransport(opts);
    const res = await http.speech(speechRequest('x'), new AbortController().signal);
    expect(Array.from(res.body)).toEqual([0x48, 0x65, 0x6c, 0x6c, 0x6f]);
  });

  it('content-type 非 json 时原样透传二进制', async () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(bytes, { headers: { 'content-type': 'audio/mpeg' } })),
    );
    const http = new HttpTransport(opts);
    const res = await http.speech(speechRequest('x'), new AbortController().signal);
    expect(res.body).toEqual(bytes);
  });

  it('HTTP 非 2xx → UpstreamError 且带 status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('oops', { status: 429 })));
    const http = new HttpTransport(opts);
    const err = await http.chat(textRequest('x'), new AbortController().signal).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UpstreamError);
    expect((err as UpstreamError).status).toBe(429);
  });

  it('网络异常 → TransportError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('ECONNREFUSED');
      }),
    );
    const http = new HttpTransport(opts);
    await expect(http.chat(textRequest('x'), new AbortController().signal)).rejects.toBeInstanceOf(
      TransportError,
    );
  });

  it('AbortSignal.timeout 触发 → TransportError（DOMException TimeoutError）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('timeout', 'TimeoutError');
      }),
    );
    const http = new HttpTransport(opts);
    await expect(http.chat(textRequest('x'), new AbortController().signal)).rejects.toBeInstanceOf(
      TransportError,
    );
  });

  it('缺少 apiKey 时拒绝发起真实请求 → ValidationError', async () => {
    const http = new HttpTransport({ ...opts, apiKey: '' });
    await expect(http.chat(textRequest('x'), new AbortController().signal)).rejects.toBeInstanceOf(
      ValidationError,
    );
  });

  it('非法 hex → UpstreamError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ data: { audio: '4z' } }), {
        headers: { 'content-type': 'application/json' },
      })),
    );
    const http = new HttpTransport(opts);
    await expect(http.speech(speechRequest('x'), new AbortController().signal)).rejects.toBeInstanceOf(
      UpstreamError,
    );
  });

  it('speech POST tts 路径并带 voice_setting/audio_setting', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: { audio: 'ff' } }), {
      headers: { 'content-type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const http = new HttpTransport(opts);
    await http.speech(speechRequest('x'), new AbortController().signal);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://api.minimax.chat/v1/t2a_v2');
    const payload = JSON.parse(String(init.body)) as Record<string, Record<string, unknown>>;
    expect(payload.audio_setting.sample_rate).toBe(32000);
    expect(payload.voice_setting.voice_id).toBe('female-shaonv');
  });
});

describe('mock-corpus：分类与人格投影', () => {
  it('classifyIntent 命中六个桶，落空归 smalltalk', () => {
    expect(classifyIntent('你到底是谁')).toBe('identity');
    expect(classifyIntent('尸检报告在哪')).toBe('evidence');
    expect(classifyIntent('我信任你')).toBe('trust');
    expect(classifyIntent('你在撒谎')).toBe('hostility');
    expect(classifyIntent('还有谁有动机')).toBe('suspects');
    expect(classifyIntent('今天天气不错')).toBe('smalltalk');
  });

  it('composeMockReply 含口头禅与情绪标记，总长 ≤120 码点', () => {
    const persona = { id: 'shen-yan', catchphrases: ['证据不会说谎', '把检材给我'] };
    const out = composeMockReply({ persona, emotion: 'calm', userText: '证据呢', turnIndex: 1 });
    expect(persona.catchphrases.some((c) => out.includes(c))).toBe(true);
    expect(out).toMatch(/（语气：.+）$/);
    expect([...out].length).toBeLessThanOrEqual(120);
  });

  it('personaFromSystemMessages 反解析 id 与口头禅', () => {
    const system = '人格：沈砚（id：shen-yan）\n口头禅：证据不会说谎、尸体比证人诚实';
    const p = personaFromSystemMessages([{ role: 'system', content: system }]);
    expect(p.id).toBe('shen-yan');
    expect(p.catchphrases).toContain('证据不会说谎');
    expect(p.catchphrases).toContain('尸体比证人诚实');
  });
});

describe('WAV：parseWavHeader 合法性', () => {
  it('长度 < 44 → ValidationError', () => {
    expect(() => parseWavHeader(new Uint8Array(10))).toThrow(ValidationError);
  });

  it('magic 不匹配 → ValidationError', () => {
    expect(() => parseWavHeader(new Uint8Array(44))).toThrow(ValidationError);
  });

  it('合法头返回四元组且 dataBytes = byteLength - 44', () => {
    const dur = estimateDurationMs('证据不会说谎', 1.0);
    const bytes = synthMockSpeech(
      '证据不会说谎',
      { voiceId: 'v', speed: 1.0, vol: 5.0, pitch: 0, emotion: 'calm' },
      dur,
    );
    expect(parseWavHeader(bytes)).toEqual({
      sampleRate: 16000,
      channels: 1,
      bitsPerSample: 16,
      dataBytes: bytes.byteLength - 44,
    });
  });
});