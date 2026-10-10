import { INVALID_REQUEST, PARSE_ERROR, JsonRpcError } from "./errors.js";
import type { JsonRpcFailure, JsonRpcNotification, JsonRpcRequest, RequestId } from "./types.js";

export const INVALID_REQUEST_ID = "__invalid_request__";
export const BATCH_ID = "__batch__";
export const PARSE_ERROR_ID = "__parse_error__";

export type DecodeResult =
  | { kind: "request"; msg: JsonRpcRequest }
  | { kind: "notification"; msg: JsonRpcNotification }
  | { kind: "response"; id: RequestId; result?: unknown; error?: unknown }
  | {
      kind: "invalid";
      id: RequestId | typeof INVALID_REQUEST_ID;
      code: number;
      message: string;
      data?: unknown;
    }
  | { kind: "batch"; id: typeof BATCH_ID }
  | { kind: "ignore" };

/** Canonical object guard for this package; parsed JSON envelopes narrow through this once. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOwn(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function echoId(rawId: unknown): RequestId | typeof INVALID_REQUEST_ID {
  return typeof rawId === "string" || typeof rawId === "number" ? rawId : INVALID_REQUEST_ID;
}

function invalid(id: RequestId | typeof INVALID_REQUEST_ID, message: string, data?: unknown): DecodeResult {
  return { kind: "invalid", id, code: INVALID_REQUEST, message, data };
}

export function decodeEnvelope(input: unknown): DecodeResult {
  if (Array.isArray(input)) {
    return { kind: "batch", id: BATCH_ID };
  }
  if (typeof input !== "object" || input === null) {
    return invalid(INVALID_REQUEST_ID, "Invalid JSON-RPC envelope", {
      reason: "Input is not an object",
    });
  }
  const obj = input as Record<string, unknown>;
  const hasId = hasOwn(obj, "id");
  const rawId = obj["id"];
  const hasMethod = hasOwn(obj, "method") && typeof obj["method"] === "string";
  const method = obj["method"] as string | undefined;

  if (obj["jsonrpc"] !== "2.0") {
    return invalid(echoId(rawId), "Invalid JSON-RPC envelope", { reason: "jsonrpc must be \"2.0\"" });
  }

  if (hasMethod) {
    if (hasId) {
      if (rawId === null || (typeof rawId !== "string" && typeof rawId !== "number")) {
        return invalid(INVALID_REQUEST_ID, "Invalid JSON-RPC envelope", {
          reason: "id must be a string or number, never null",
        });
      }
      const msg: JsonRpcRequest = {
        jsonrpc: "2.0",
        id: rawId,
        method: method as string,
      };
      if (hasOwn(obj, "params")) {
        const params = obj["params"];
        if (typeof params !== "object" || params === null || Array.isArray(params)) {
          return invalid(rawId, "Invalid JSON-RPC envelope", {
            reason: "params must be an object when present",
          });
        }
        msg.params = params as Record<string, unknown>;
      }
      return { kind: "request", msg };
    }
    const note: JsonRpcNotification = { jsonrpc: "2.0", method: method as string };
    if (hasOwn(obj, "params")) {
      const params = obj["params"];
      if (typeof params !== "object" || params === null || Array.isArray(params)) {
        return invalid(INVALID_REQUEST_ID, "Invalid JSON-RPC envelope", {
          reason: "params must be an object when present",
        });
      }
      note.params = params as Record<string, unknown>;
    }
    return { kind: "notification", msg: note };
  }

  if (hasId) {
    if (rawId === null || (typeof rawId !== "string" && typeof rawId !== "number")) {
      return invalid(INVALID_REQUEST_ID, "Invalid JSON-RPC envelope", {
        reason: "id must be a string or number, never null",
      });
    }
    const hasResult = hasOwn(obj, "result");
    const hasError = hasOwn(obj, "error");
    if (hasResult && hasError) {
      return invalid(rawId, "Invalid JSON-RPC envelope", {
        reason: "response must not carry both result and error",
      });
    }
    if (!hasResult && !hasError) {
      return invalid(rawId, "Invalid JSON-RPC envelope", {
        reason: "response must carry result or error",
      });
    }
    if (hasResult) return { kind: "response", id: rawId, result: obj["result"] };
    return { kind: "response", id: rawId, error: obj["error"] };
  }

  if (hasOwn(obj, "result") || hasOwn(obj, "error")) {
    return invalid(INVALID_REQUEST_ID, "Invalid JSON-RPC envelope", {
      reason: "response is missing id",
    });
  }

  return { kind: "ignore" };
}

export type ParseResult =
  | { ok: true; value: unknown }
  | { ok: false; error: JsonRpcFailure };

export function parseLine(line: string): ParseResult {
  try {
    return { ok: true, value: JSON.parse(line) as unknown };
  } catch (err) {
    const message = err instanceof JsonRpcError ? err.message : "Parse error";
    return {
      ok: false,
      error: {
        jsonrpc: "2.0",
        id: PARSE_ERROR_ID,
        error: { code: PARSE_ERROR, message },
      },
    };
  }
}
