/**
 * 错误层级：所有网络/协议/降级失败都必须归一到这些类型，
 * 以便上层用 instanceof 做确定性分支，绝不依赖错误字符串。
 */

export type RuntimeMode = 'live' | 'mock';

export class AgentError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = new.target.name;
    this.code = code;
  }
}

/** 缺少 API Key、BaseURL 非法等启动前置条件缺失 */
export class ConfigError extends AgentError {
  constructor(message: string) {
    super('E_CONFIG', message);
  }
}

/** 请求超时或网络不可达 —— 唯一允许触发自动降级的错误 */
export class TransportError extends AgentError {
  constructor(message: string, options?: { cause?: unknown }) {
    super('E_TRANSPORT', message);
    if (options?.cause !== undefined) this.cause = options.cause;
  }
}

/** 上游返回非 2xx，或响应体无法解析 */
export class UpstreamError extends AgentError {
  constructor(message: string, readonly status?: number) {
    super('E_UPSTREAM', message);
  }
}

/** 调用方入参违反契约（例如 speed 越界） */
export class ValidationError extends AgentError {
  constructor(message: string) {
    super('E_VALIDATION', message);
  }
}

export function isTransportFailure(err: unknown): err is TransportError {
  return err instanceof TransportError;
}

/** 把任意抛出物归一为 AgentError，避免上层处理 unknown 分支 */
export function normalizeError(err: unknown): AgentError {
  if (err instanceof AgentError) return err;
  if (err instanceof Error) return new AgentError('E_UNKNOWN', err.message);
  return new AgentError('E_UNKNOWN', String(err));
}
