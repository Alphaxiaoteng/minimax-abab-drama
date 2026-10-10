import { INTERNAL_ERROR, JsonRpcError } from "./errors.js";
import type {
  JsonRpcFailure,
  JsonRpcNotification,
  JsonRpcSuccess,
  RequestId,
} from "./types.js";

export function success(id: RequestId, result: Record<string, unknown>): JsonRpcSuccess {
  return { jsonrpc: "2.0", id, result };
}

export function failure(
  id: RequestId,
  code: number,
  message: string,
  data?: unknown,
): JsonRpcFailure {
  const error: { code: number; message: string; data?: unknown } = { code, message };
  if (data !== undefined) error.data = data;
  return { jsonrpc: "2.0", id, error };
}

export function notification(
  method: string,
  params?: Record<string, unknown>,
): JsonRpcNotification {
  const msg: JsonRpcNotification = { jsonrpc: "2.0", method };
  if (params !== undefined) msg.params = params;
  return msg;
}

export function fromError(id: RequestId, err: unknown): JsonRpcFailure {
  if (err instanceof JsonRpcError) {
    return failure(id, err.code, err.message, err.data);
  }
  const message = err instanceof Error ? err.message : String(err);
  return failure(id, INTERNAL_ERROR, "Internal error", { message });
}
