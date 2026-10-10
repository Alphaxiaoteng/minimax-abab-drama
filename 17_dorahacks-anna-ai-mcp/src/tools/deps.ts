import type { NetIntelConfig } from "../config.js";
import { ResponseCache } from "../net/cache.js";
import type { FeedEngine } from "../net/feeds.js";
import type { HttpClient } from "../net/http.js";
import type { SourceAdapter } from "../net/types.js";
import type { SubscriptionHub } from "../resources/subscriptions.js";

/**
 * The single dependency bundle every feature surface (tools, resources,
 * prompts) is registered against. Pinned here so all slices import ONE shape
 * instead of re-deriving it — the previous drift source.
 */
export interface ToolDeps {
  engine: FeedEngine;
  sources: SourceAdapter[];
  cache: ResponseCache;
  http: HttpClient;
  offline: boolean;
  config: NetIntelConfig;
  /** invoked with a `digest|<hex>` cache key whenever a search writes a markdown
   *  digest, so subscribed `netintel://feed/{key}` resources can be updated */
  onCacheTouch?: (key: string) => void;
}

export type ResourceDeps = ToolDeps & {
  subscriptions: SubscriptionHub;
};

export type PromptDeps = ToolDeps;

/** deterministic synthetic key for the aggregate digest of a query */
export function digestKey(
  cache: ResponseCache,
  q: string,
  limit: number,
  since: string | undefined,
  tags: string[] | undefined,
): string {
  return ResponseCache.key(["digest", q, String(limit), since, (tags ?? []).join(",")]);
}
