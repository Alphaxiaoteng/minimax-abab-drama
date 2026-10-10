/**
 * 真实 HTTP 端到端测试：startServer({port:0}) 随机端口起服务，
 * 用 fetch 跑完整闭环（health→personas→session→turn→非法输入→路径穿越→静态资源），
 * 最后必须真的关掉服务器。全程离线 mock，绝不触碰真实网络与凭证。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { startServer } from './index.js';
import { createApiDeps, handleApiRequest } from './api.js';
import type { ApiResponsePayload } from './api.js';
import { defaultScreenplay } from '../index.js';
import type { DramaEngineLike, ServerHandle } from '../core/contracts.js';

let handle: ServerHandle;

beforeAll(async () => {
  // 强制离线 mock：测试绝不触碰真实网络
  process.env.AGENT_FORCE_OFFLINE = '1';
  delete process.env.MINIMAX_API_KEY;
  handle = await startServer({ port: 0, host: '127.0.0.1' });
});

afterAll(async () => {
  await handle.close();
});

function url(path: string): string {
  return `http://127.0.0.1:${handle.port}${path}`;
}

async function getJson(path: string): Promise<{ status: number; payload: Record<string, unknown> }> {
  const res = await fetch(url(path));
  return { status: res.status, payload: (await res.json()) as Record<string, unknown> };
}

async function postJson(
  path: string,
  body: unknown,
): Promise<{ status: number; payload: Record<string, unknown>; raw: string }> {
  const res = await fetch(url(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const raw = await res.text();
  return { status: res.status, payload: JSON.parse(raw) as Record<string, unknown>, raw };
}

describe('server：真实 HTTP 闭环', () => {
  it('GET /api/health → ok:true、mode、personas 数组、version', async () => {
    const { status, payload } = await getJson('/api/health');
    expect(status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.mode).toBe('mock');
    expect(Array.isArray(payload.personas)).toBe(true);
    expect((payload.personas as string[]).length).toBeGreaterThan(0);
    expect(typeof payload.version).toBe('string');
  });

  it('GET /api/personas → 全量返回含 openingLine/tagline/voice', async () => {
    const { status, payload } = await getJson('/api/personas');
    expect(status).toBe(200);
    const personas = payload.personas as Record<string, unknown>[];
    expect(personas.length).toBe(3);
    for (const p of personas) {
      expect(typeof p.id).toBe('string');
      expect(typeof p.openingLine).toBe('string');
      expect(typeof p.tagline).toBe('string');
      expect(p.voice).toBeDefined();
    }
  });

  it('GET /api/screenplay → 结构与契约一致且真凶唯一', async () => {
    const { status, payload } = await getJson('/api/screenplay');
    expect(status).toBe(200);
    const sp = payload.screenplay as Record<string, unknown>;
    expect(Array.isArray(sp.clues)).toBe(true);
    expect(Array.isArray(sp.suspects)).toBe(true);
    const suspects = sp.suspects as { isCulprit: boolean }[];
    expect(suspects.filter((s) => s.isCulprit).length).toBe(1);
  });

  it('POST /api/session → sessionId + opening.speech WAV base64', async () => {
    const { status, payload } = await postJson('/api/session', { personaId: 'shen-yan' });
    expect(status).toBe(200);
    const sessionId = payload.sessionId as string;
    expect(sessionId.length).toBeGreaterThan(0);
    const opening = payload.opening as {
      speech: { dataUrl: string; mimeType: string; durationMs: number };
    };
    expect(opening.speech.dataUrl.startsWith('data:audio/')).toBe(true);
    expect(opening.speech.dataUrl).toContain('base64,');
    expect(opening.speech.durationMs).toBeGreaterThanOrEqual(0);
    const state = payload.state as { sessionId: string; turns: unknown[]; ended: boolean };
    expect(state.sessionId).toBe(sessionId);
    expect(state.turns.length).toBeGreaterThan(0);
  });

  it('POST /api/turn → state.turns 递增且返回 WAV base64', async () => {
    const session = await postJson('/api/session', { personaId: 'shen-yan' });
    const sessionId = session.payload.sessionId as string;
    const before = (session.payload.state as { turns: unknown[] }).turns.length;

    const turn = await postJson('/api/turn', { sessionId, text: '我怀疑账簿里少了三页。' });
    expect(turn.status).toBe(200);
    const state = turn.payload.state as { turns: unknown[] };
    expect(state.turns.length).toBeGreaterThan(before);
    const speech = turn.payload.speech as { dataUrl: string };
    expect(speech.dataUrl.startsWith('data:audio/')).toBe(true);
  });

  it('非法 JSON → 400 且响应体不含堆栈', async () => {
    const res = await fetch(url('/api/turn'), { method: 'POST', body: '{bad json' });
    expect(res.status).toBe(400);
    const text = await res.text();
    expect(text).not.toMatch(/\bat\s+\S+\.\S+:\d+/);
    expect(text).not.toMatch(/stack/i);
  });

  it('未知 personaId → 400；缺字段 → 400', async () => {
    const unknown = await postJson('/api/session', { personaId: 'ghost' });
    expect(unknown.status).toBe(400);
    expect(typeof unknown.payload.error).toBe('string');
    const missing = await postJson('/api/session', {});
    expect(missing.status).toBe(400);
  });

  it('方法不匹配 → 405；未知路由 → 404', async () => {
    const wrong = await fetch(url('/api/health'), { method: 'POST' });
    expect(wrong.status).toBe(405);
    const unknown = await fetch(url('/api/nope'));
    expect(unknown.status).toBe(404);
  });

  it('路径穿越（含编码变体）→ 403', async () => {
    // WHATWG URL 会把 /../package.json 归一为 /package.json（只会 404，测不到防护），
    // 用编码斜杠绕过归一，服务端解码后必须命中 '..' 拒绝分支。
    const encoded = await fetch(url('/..%2F..%2Fpackage.json'));
    const dotDot = await fetch(url('/%2e%2e%2F%2e%2e%2Fpackage.json'));
    expect(dotDot.status).toBe(403);
  });

  it('冒号段等文件系统绝对路径形态 → 403', async () => {
    const colon = await fetch(url('/file:etc/passwd'));
    expect(colon.status).toBe(403);
  });

  it('GET / → index.html；js/css/webmanifest MIME 正确且带 nosniff', async () => {
    const home = await fetch(url('/'));
    expect(home.status).toBe(200);
    expect(home.headers.get('content-type')).toContain('text/html');
    expect(await home.text()).toContain('沉浸式');
    expect(home.headers.get('x-content-type-options')).toBe('nosniff');

    const js = await fetch(url('/app.js'));
    expect(js.headers.get('content-type')).toContain('javascript');

    const css = await fetch(url('/styles.css'));
    expect(css.headers.get('content-type')).toContain('text/css');

    const manifest = await fetch(url('/manifest.webmanifest'));
    expect(manifest.headers.get('content-type')).toContain('application/manifest+json');
  });

  it('静态资源缺失 → 404', async () => {
    const res = await fetch(url('/no-such-file.xyz'));
    expect(res.status).toBe(404);
  });

  it('close() 之后端口不再接受连接', async () => {
    const second = await startServer({ port: 0, host: '127.0.0.1' });
    const deadPort = second.port;
    await second.close();
    await expect(fetch(`http://127.0.0.1:${deadPort}/api/health`)).rejects.toBeTruthy();
  });
});

/** 已结束会话的引擎测试替身：只为验证 409 分支，不承载任何产品逻辑 */
function endedEngineStub(): DramaEngineLike {
  return {
    state: {
      sessionId: 'ended-1',
      personaId: 'shen-yan',
      screenplayId: defaultScreenplay.id,
      phase: 'resolution',
      trust: 90,
      tension: 70,
      revealedClueIds: [],
      turns: [],
      ended: true,
    },
    start: () => Promise.reject(new Error('测试替身不应被调用 start')),
    send: () => Promise.reject(new Error('测试替身不应被调用 send')),
    events: () => [],
  };
}

describe('api：纯函数处理（不启端口直测）', () => {
  it('已结束的 sessionId → 409', async () => {
    const deps = createApiDeps({ forceOffline: true });
    deps.sessions.set('ended-1', { personaId: 'shen-yan', engine: endedEngineStub() });
    const resp = await handleApiRequest(
      {
        method: 'POST',
        url: '/api/turn',
        body: JSON.stringify({ sessionId: 'ended-1', text: '你好' }),
      },
      deps,
    );
    expect(resp.status).toBe(409);
    expect(resp.body).toContain('已结束');
  });

  it('不存在的 sessionId → 404', async () => {
    const deps = createApiDeps({ forceOffline: true });
    const resp = await handleApiRequest(
      {
        method: 'POST',
        url: '/api/turn',
        body: JSON.stringify({ sessionId: 'nope', text: '你好' }),
      },
      deps,
    );
    expect(resp.status).toBe(404);
  });

  it('纯函数层完整闭环：session→turn 状态推进且返回 data URL', async () => {
    const deps = createApiDeps({ forceOffline: true });
    const created: ApiResponsePayload = await handleApiRequest(
      { method: 'POST', url: '/api/session', body: JSON.stringify({ personaId: 'shen-yan' }) },
      deps,
    );
    expect(created.status).toBe(200);
    const createdBody = JSON.parse(created.body) as {
      sessionId: string;
      state: { turns: unknown[] };
    };
    const turned = await handleApiRequest(
      {
        method: 'POST',
        url: '/api/turn',
        body: JSON.stringify({ sessionId: createdBody.sessionId, text: '案发当晚你在哪？' }),
      },
      deps,
    );
    expect(turned.status).toBe(200);
    const turnBody = JSON.parse(turned.body) as {
      speech: { dataUrl: string };
      state: { turns: unknown[] };
    };
    expect(turnBody.speech.dataUrl).toContain('data:audio/');
    expect(turnBody.state.turns.length).toBeGreaterThan(createdBody.state.turns.length);
  });

  it('请求体为空串 → 400', async () => {
    const deps = createApiDeps({ forceOffline: true });
    const resp = await handleApiRequest({ method: 'POST', url: '/api/session', body: '' }, deps);
    expect(resp.status).toBe(400);
  });
});