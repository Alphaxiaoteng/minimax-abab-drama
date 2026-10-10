import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ResponseCache } from "../cache.js";
import type { HttpClient } from "../http.js";
import type { RawItem, SearchQuery } from "../types.js";

/** Constructor bundle handed to every source adapter (contract §7). */
export interface SourceOptions {
  http: HttpClient;
  cache: ResponseCache;
  fixtureDir: string;
  offline: boolean;
}

export const MAX_LIMIT = 50;

export function clampLimit(limit: number): number {
  return Math.max(1, Math.min(MAX_LIMIT, Math.trunc(limit)));
}

/** Cache key for a per-source query. Mirrors the recorded fixture filenames byte-for-byte. */
export function queryCacheKey(sourceId: string, query: SearchQuery): string {
  return ResponseCache.key([
    sourceId,
    query.q,
    query.limit,
    query.since,
    (query.tags ?? []).join(","),
  ]);
}

/**
 * Reads a fixture payload as raw text. Tries the exact cache key, then the
 * `_default.json` fallback. Returns `undefined` when neither file exists —
 * the caller treats that as an empty, non-cacheable result.
 */
export function readFixture(
  fixtureDir: string,
  sourceId: string,
  cacheKey: string,
): string | undefined {
  const dir = join(fixtureDir, sourceId);
  for (const candidate of [join(dir, `${cacheKey}.json`), join(dir, "_default.json")]) {
    try {
      const text = readFileSync(candidate, "utf8");
      if (text.trim().length > 0) return text;
    } catch {
      // missing this candidate; fall through to the next
    }
  }
  return undefined;
}

export interface FreshOutcome {
  items: RawItem[];
  /** failures are never cached; successful parses (even empty) are */
  cacheable: boolean;
}

/**
 * Cache read-through shared by all adapters: a cache hit returns immediately;
 * otherwise `fresh()` produces items and they are stored only when the fetch
 * itself succeeded, so a transient upstream error never poisons the cache.
 */
export async function readThrough(
  cache: ResponseCache,
  key: string,
  fresh: () => Promise<FreshOutcome>,
): Promise<RawItem[]> {
  const hit = cache.get(key);
  if (Array.isArray(hit)) return hit as RawItem[];
  const outcome = await fresh();
  if (outcome.cacheable) cache.set(key, outcome.items);
  return outcome.items;
}

/** Runs a parse that may throw on malformed data, degrading to an empty result. */
export function safeParse(sourceId: string, parse: () => RawItem[]): FreshOutcome {
  try {
    return { items: parse(), cacheable: true };
  } catch {
    return { items: [], cacheable: false };
  }
}
