import { INVALID_PARAMS, JsonRpcError } from "./errors.js";

export interface PagedResult<T> {
  page: T[];
  nextCursor?: string;
}

export function encodeCursor(offset: number): string {
  return Buffer.from(JSON.stringify({ o: offset }), "utf8").toString("base64url");
}

export function decodeCursor(cursor: unknown, total: number, pageSize: number): number {
  if (cursor === undefined || cursor === null) return 0;
  if (typeof cursor !== "string") throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
  let offset: unknown;
  try {
    const parsed: unknown = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
    }
    offset = (parsed as Record<string, unknown>).o;
  } catch (err) {
    if (err instanceof JsonRpcError) throw err;
    throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
  }
  if (typeof offset !== "number" || !Number.isInteger(offset) || offset < 0) {
    throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
  }
  if (pageSize > 0 && total > 0 && offset > total) {
    throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
  }
  if (total === 0 && offset > 0) {
    throw new JsonRpcError(INVALID_PARAMS, "Invalid cursor");
  }
  return offset;
}

export function paginate<T>(items: T[], cursor: unknown, pageSize: number): PagedResult<T> {
  const offset = decodeCursor(cursor, items.length, pageSize);
  const size = pageSize > 0 ? pageSize : items.length;
  const page = items.slice(offset, offset + size);
  const next = offset + size;
  return next < items.length ? { page, nextCursor: encodeCursor(next) } : { page };
}
