export class JsonRpcError extends Error {
  readonly code: number;
  readonly data?: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "JsonRpcError";
    this.code = code;
    this.data = data;
  }
}

export const PARSE_ERROR = -32700;
export const INVALID_REQUEST = -32600;
export const METHOD_NOT_FOUND = -32601;
export const INVALID_PARAMS = -32602;
export const INTERNAL_ERROR = -32603;
export const RESOURCE_NOT_FOUND = -32002;

export function parseError(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(PARSE_ERROR, message, data);
}

export function invalidRequest(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(INVALID_REQUEST, message, data);
}

export function methodNotFound(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(METHOD_NOT_FOUND, message, data);
}

export function invalidParams(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(INVALID_PARAMS, message, data);
}

export function internalError(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(INTERNAL_ERROR, message, data);
}

export function resourceNotFound(message: string, data?: unknown): JsonRpcError {
  return new JsonRpcError(RESOURCE_NOT_FOUND, message, data);
}
