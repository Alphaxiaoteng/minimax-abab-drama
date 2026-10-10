/**
 * 纯函数 API 处理器：不依赖 node:http 对象。
 * 传入 {method, url, body} 与注入依赖（deps）即可断言路由行为，
 * 因此单元测试可以不开端口直接测试完整请求-响应闭环。
 */

import type { AgentConfig, ConfigOverrides } from '../core/config.js';
import { loadConfig } from '../core/config.js';
import { AgentError } from '../core/errors.js';
import type {
  DramaEngineLike,
  MiniMaxClientLike,
  PersonaRegistry,
} from '../core/contracts.js';
import type {
  DialogueResponse,
  DialogueTurn,
  DramaEvent,
  DramaState,
  Persona,
  Screenplay,
  SpeechResult,
} from '../core/types.js';
// 跨切片运行时值统一从根 barrel 导入（export * 汇聚 personas/minimax/engine/eval）。
// defaultScreenplay 的具体归属模块由并行切片裁决，本文件不关心其源模块。
import { DramaEngine, MiniMaxClient, defaultScreenplay, personaRegistry } from '../index.js';

/** API 版本，供健康检查与前端兼容性提示 */
export const API_VERSION = '1.0.0';

/** 请求的最小结构体（与 node:http 解耦） */
export interface ApiRequestPayload {
  readonly method: string;
  readonly url: string;
  readonly body: string;
}

/** 响应的最小结构体（与 node:http 解耦） */
export interface ApiResponsePayload {
  readonly status: number;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: string;
}

/** 会话表条目：引擎实例 + 归属人格 */
export interface SessionEntry {
  readonly personaId: string;
  readonly engine: DramaEngineLike;
}

/** 语音结果的可序列化形态：音频以 data URL（base64）回传 */
export interface SerializedSpeech {
  readonly dataUrl: string;
  readonly mimeType: string;
  readonly durationMs: number;
  readonly source: 'live' | 'mock';
  readonly latencyMs: number;
}

/** DialogueResponse 的 JSON 安全形态（Uint8Array → base64 data URL） */
export interface SerializedDialogueResponse {
  readonly turn: DialogueTurn;
  readonly speech: SerializedSpeech;
  readonly state: DramaState;
  readonly events: readonly DramaEvent[];
  readonly degraded: boolean;
}

/** 注入依赖包：会话表以闭包 Map 形式存活于服务器实例内 */
export interface ApiDeps {
  readonly personas: PersonaRegistry;
  readonly screenplay: Screenplay;
  readonly config: AgentConfig;
  readonly sessions: Map<string, SessionEntry>;
  readonly makeClient: () => MiniMaxClientLike;
  readonly makeEngine: (persona: Persona, client: MiniMaxClientLike) => DramaEngineLike;
}

/**
 * 构造依赖包。每个服务器实例调用一次，sessions 即为该实例的闭包会话表。
 * 无 API Key 时 loadConfig 自动选择 mock 模式，绝不真实外呼。
 */
export function createApiDeps(overrides: ConfigOverrides = {}): ApiDeps {
  const config = loadConfig(process.env, overrides);
  const sessions: Map<string, SessionEntry> = new Map();
  return {
    personas: personaRegistry,
    screenplay: defaultScreenplay,
    config,
    sessions,
    makeClient: () => new MiniMaxClient({ config }),
    makeEngine: (persona, client) =>
      new DramaEngine({ persona, screenplay: defaultScreenplay, client }),
  };
}

/** 带 HTTP 状态码的预期内错误；绝不携带堆栈 */
class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

/** 统一 JSON 响应封装（多处调用需锁步行为） */
function json(status: number, payload: unknown): ApiResponsePayload {
  return {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  };
}

function parseJsonObject(raw: string): Record<string, unknown> {
  if (raw.trim().length === 0) throw new ApiError(400, '请求体不能为空');
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new ApiError(400, '请求体必须是合法 JSON');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new ApiError(400, '请求体必须是 JSON 对象');
  }
  return parsed as Record<string, unknown>;
}

function requireString(obj: Record<string, unknown>, key: string): string {
  const value = obj[key];
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new ApiError(400, `字段 ${key} 必须是非空字符串`);
  }
  return value.trim();
}

/** 音频字节 → data URL；mock 为 WAV，live 取决于上游 MIME */
function toDataUrl(speech: SpeechResult): string {
  const mime = speech.mimeType.length > 0 ? speech.mimeType : 'audio/wav';
  return `data:${mime};base64,${Buffer.from(speech.audio).toString('base64')}`;
}

function serializeResponse(resp: DialogueResponse): SerializedDialogueResponse {
  return {
    turn: resp.turn,
    speech: {
      dataUrl: toDataUrl(resp.speech),
      mimeType: resp.speech.mimeType,
      durationMs: resp.speech.durationMs,
      source: resp.speech.source,
      latencyMs: resp.speech.latencyMs,
    },
    state: resp.state,
    events: resp.events,
    degraded: resp.degraded,
  };
}

async function handleCreateSession(rawBody: string, deps: ApiDeps): Promise<ApiResponsePayload> {
  const body = parseJsonObject(rawBody);
  const personaId = requireString(body, 'personaId');
  // 未知 id 由 personaRegistry.byId 抛 ConfigError（E_CONFIG），统一转 400
  const persona = deps.personas.byId(personaId);
  const client = deps.makeClient();
  const engine = deps.makeEngine(persona, client);
  const opening = await engine.start();
  deps.sessions.set(engine.state.sessionId, { personaId, engine });
  return json(200, {
    sessionId: engine.state.sessionId,
    state: opening.state,
    opening: serializeResponse(opening),
  });
}

async function handleTurn(rawBody: string, deps: ApiDeps): Promise<ApiResponsePayload> {
  const body = parseJsonObject(rawBody);
  const sessionId = requireString(body, 'sessionId');
  const text = requireString(body, 'text');
  const entry = deps.sessions.get(sessionId);
  if (entry === undefined) throw new ApiError(404, '会话不存在或已过期');
  if (entry.engine.state.ended) throw new ApiError(409, '本场戏已结束');
  const resp = await entry.engine.send({ sessionId, userText: text });
  return json(200, serializeResponse(resp));
}

/** 把任意抛出物归一为安全响应：只暴露受控中文信息，绝不泄露堆栈 */
function toErrorResponse(err: unknown): ApiResponsePayload {
  if (err instanceof ApiError) return json(err.status, { error: err.message });
  if (err instanceof AgentError) {
    if (err.code === 'E_CONFIG' || err.code === 'E_VALIDATION') {
      return json(400, { error: err.message });
    }
    return json(500, { error: '服务器内部错误' });
  }
  return json(500, { error: '服务器内部错误' });
}

/** 路由 → 允许方法。命中但方法不符即 405；未命中即 404。 */
const ROUTE_METHODS: Record<string, string> = {
  '/api/health': 'GET',
  '/api/personas': 'GET',
  '/api/screenplay': 'GET',
  '/api/session': 'POST',
  '/api/turn': 'POST',
};

/** 请求分发入口：纯函数，可直接单测，也可由 index.ts 包装进 node:http */
export async function handleApiRequest(
  req: ApiRequestPayload,
  deps: ApiDeps,
): Promise<ApiResponsePayload> {
  const method = req.method.toUpperCase();
  // 去掉查询串与片段，只保留路由本体
  const path = (req.url.split('?')[0] ?? '/').split('#')[0] ?? '/';
  try {
    if (method === 'GET' && path === '/api/health') {
      return json(200, {
        ok: true,
        mode: deps.config.mode,
        personas: deps.personas.ids(),
        version: API_VERSION,
      });
    }
    if (method === 'GET' && path === '/api/personas') {
      // 全量返回：前端要用 openingLine 与 tagline，连同 voice 一并给出
      return json(200, { personas: deps.personas.all });
    }
    if (method === 'GET' && path === '/api/screenplay') {
      return json(200, { screenplay: deps.screenplay });
    }
    if (method === 'POST' && path === '/api/session') {
      return await handleCreateSession(req.body, deps);
    }
    if (method === 'POST' && path === '/api/turn') {
      return await handleTurn(req.body, deps);
    }
    if (ROUTE_METHODS[path] !== undefined) {
      throw new ApiError(405, '方法不允许');
    }
    throw new ApiError(404, '未知路由');
  } catch (err) {
    return toErrorResponse(err);
  }
}