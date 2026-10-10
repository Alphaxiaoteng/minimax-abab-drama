/**
 * 运行时配置解析。优先级：显式传参 > 环境变量 > 默认值。
 *
 * 关键契约：`apiKey` 为空时 mode 必为 'mock'，绝不在缺少密钥时发起真实请求，
 * 也绝不把密钥写进日志/报告。
 */

import { MINIMAX_DEFAULTS } from './constants.js';
import { ConfigError } from './errors.js';

export interface AgentConfig {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly textModel: string;
  readonly speechModel: string;
  readonly requestTimeoutMs: number;
  readonly maxRetries: number;
  /** 'live' 走真实 HTTPS；'mock' 走进程内确定性传输层 */
  readonly mode: 'live' | 'mock';
  /** 强制降级开关：用于评测「真实失败 → mock 兜底」这条路径 */
  readonly forceOffline: boolean;
}

export interface ConfigOverrides {
  readonly baseUrl?: string;
  readonly apiKey?: string;
  readonly textModel?: string;
  readonly speechModel?: string;
  readonly requestTimeoutMs?: number;
  readonly maxRetries?: number;
  readonly forceOffline?: boolean;
}

interface EnvLike {
  readonly [key: string]: string | undefined;
}

/** 读取 MiniMax 凭证：优先赛事专属变量名，其次官方通用变量名 */
function readApiKey(env: EnvLike): string {
  return env.MINIMAX_API_KEY ?? env.MINIMAX_GROUP_API_KEY ?? '';
}

export function loadConfig(env: EnvLike = process.env, overrides: ConfigOverrides = {}): AgentConfig {
  const apiKey = overrides.apiKey ?? readApiKey(env);
  const baseUrl = normalizeBaseUrl(overrides.baseUrl ?? env.MINIMAX_BASE_URL ?? MINIMAX_DEFAULTS.baseUrl);
  const forceOffline = overrides.forceOffline ?? env.AGENT_FORCE_OFFLINE === '1';

  const timeout = overrides.requestTimeoutMs ?? Number(env.MINIMAX_TIMEOUT_MS ?? MINIMAX_DEFAULTS.requestTimeoutMs);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new ConfigError(`requestTimeoutMs 必须是正数，收到 ${timeout}`);
  }

  return {
    baseUrl,
    apiKey,
    textModel: overrides.textModel ?? env.MINIMAX_TEXT_MODEL ?? MINIMAX_DEFAULTS.textModel,
    speechModel: overrides.speechModel ?? env.MINIMAX_SPEECH_MODEL ?? MINIMAX_DEFAULTS.speechModel,
    requestTimeoutMs: timeout,
    maxRetries: overrides.maxRetries ?? MINIMAX_DEFAULTS.maxRetries,
    mode: apiKey.length > 0 && !forceOffline ? 'live' : 'mock',
    forceOffline,
  };
}

/** 暴露给 UI/报告的安全摘要：不含 apiKey 明文 */
export function publicConfigSummary(config: AgentConfig): Record<string, string | number | boolean> {
  return {
    baseUrl: config.baseUrl,
    textModel: config.textModel,
    speechModel: config.speechModel,
    mode: config.mode,
    requestTimeoutMs: config.requestTimeoutMs,
    credentialPresent: config.apiKey.length > 0,
  };
}

function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      throw new ConfigError(`baseUrl 协议必须是 http(s)，收到 ${parsed.protocol}`);
    }
    return parsed.origin + parsed.pathname.replace(/\/+$/, '');
  } catch (err) {
    if (err instanceof ConfigError) throw err;
    throw new ConfigError(`baseUrl 不是合法 URL: ${raw}`);
  }
}
