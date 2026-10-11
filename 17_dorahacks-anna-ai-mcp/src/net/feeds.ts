import type { CacheStats, ResponseCache } from "./cache.js";
import type { RawItem, SearchQuery, SourceAdapter } from "./types.js";

export interface FeedItem extends RawItem {
  source: string;
  score: number;
}

export interface ScoringBreakdown {
  matchScore: number;
  recencyScore: number;
  engagementScore: number;
  total: number;
  rrfContribution?: number;
  sourceRank?: number;
}

export interface FeedItemWithScoring extends FeedItem {
  scoring?: ScoringBreakdown;
}

export interface FeedResult {
  query: string;
  sources: string[];
  offline: boolean;
  partial: boolean;
  failedSources: { source: string; error: string }[];
  items: FeedItemWithScoring[];
  total: number;
  tookMs: number;
  cache: CacheStats;
  scoringMethod?: "rrf" | "weighted";
}

export interface FeedEngineOptions {
  sources: SourceAdapter[];
  cache: ResponseCache;
  offline?: boolean;
  now?: () => number;
  log?: (level: string, logger: string, data: unknown) => void;
}

const TITLE_WEIGHT = 1.0;
const TAG_WEIGHT = 0.5;
const SUMMARY_WEIGHT = 0.25;
const AUTHOR_WEIGHT = 0.1;

const MATCH_FACTOR = 4.0;
const RECENCY_FACTOR = 2.0;
const ENGAGEMENT_FACTOR = 1.0;

/** Splits a query into lowercase alphanumeric tokens (deduped, order-preserving). */
export function tokenize(s: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of s.toLowerCase().split(/[^a-z0-9]+/)) {
    if (raw.length === 0 || seen.has(raw)) continue;
    seen.add(raw);
    out.push(raw);
  }
  return out;
}

function contains(haystack: string | undefined, token: string): boolean {
  return haystack !== undefined && haystack.toLowerCase().includes(token);
}

function matchWeight(item: RawItem, tokens: string[]): number {
  if (tokens.length === 0) return 0;
  let hits = 0;
  for (const token of tokens) {
    if (contains(item.title, token)) hits += TITLE_WEIGHT;
    else if (item.tags?.some((t) => t.toLowerCase() === token)) hits += TAG_WEIGHT;
    else if (contains(item.summary, token)) hits += SUMMARY_WEIGHT;
    else if (contains(item.author, token)) hits += AUTHOR_WEIGHT;
  }
  return hits / Math.max(1, tokens.length);
}

function recencyWeight(item: RawItem, nowMs: number): number {
  if (item.publishedAt === undefined) return 0.25;
  const ts = Date.parse(item.publishedAt);
  if (Number.isNaN(ts)) return 0.25;
  const ageHours = Math.max(0, (nowMs - ts) / 3_600_000);
  return 1 / (1 + ageHours / 24);
}

function engagementMetric(item: RawItem): number {
  if (item.metrics === undefined) return 0;
  let sum = 0;
  for (const value of Object.values(item.metrics)) sum += value;
  return sum;
}

/**
 * Deterministic rank score: 4×match + 2×recency + 1×engagement.
 * `engagementNorm` is the log-scaled engagement already normalised by the set maximum;
 * callers that score in isolation pass 0 (the match/recency components still hold).
 */
export function scoreItem(
  item: RawItem,
  tokens: string[],
  nowMs: number,
  engagementNorm = 0,
): number {
  return (
    MATCH_FACTOR * matchWeight(item, tokens) +
    RECENCY_FACTOR * recencyWeight(item, nowMs) +
    ENGAGEMENT_FACTOR * engagementNorm
  );
}

/** Lowercase host+path, strip trailing slash and marketing params. */
export function normalizeUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url.toLowerCase();
  }
  parsed.hash = "";
  parsed.search = "";
  const path = parsed.pathname.replace(/\/+$/, "");
  return `${parsed.host.toLowerCase()}${path}`;
}

export interface FeedOutcome {
  result: FeedResult;
  onResolved?: (progress: number, total: number) => void;
}

export class FeedEngine {
  private readonly sources: SourceAdapter[];
  private readonly cache: ResponseCache;
  private readonly offline: boolean;
  private readonly nowFn: () => number;
  private readonly logFn?: (level: string, logger: string, data: unknown) => void;

  constructor(opts: FeedEngineOptions) {
    this.sources = opts.sources;
    this.cache = opts.cache;
    this.offline = opts.offline ?? false;
    this.nowFn = opts.now ?? (() => Date.now());
    this.logFn = opts.log;
  }

  get sourceIds(): string[] {
    return this.sources.map((s) => s.id);
  }

  async search(query: SearchQuery, sourceIds?: string[]): Promise<FeedResult> {
    const started = this.nowFn();
    const selected =
      sourceIds === undefined
        ? this.sources
        : this.sources.filter((s) => sourceIds.includes(s.id));

    const settled = await Promise.allSettled(selected.map((s) => s.search(query)));

    const failedSources: { source: string; error: string }[] = [];
    const byUrl = new Map<string, FeedItem>();
    let resolvedCount = 0;

    settled.forEach((outcome, index) => {
      const source = selected[index];
      if (source === undefined) return;
      if (outcome.status === "rejected") {
        const error = outcome.reason instanceof Error ? outcome.reason.message : String(outcome.reason);
        failedSources.push({ source: source.id, error });
        this.logFn?.("warning", `feed:${source.id}`, { query: query.q, error });
        return;
      }
      resolvedCount += 1;
      for (const item of outcome.value) {
        const key = normalizeUrl(item.url);
        const candidate: FeedItem = { ...item, source: source.id, score: 0 };
        const existing = byUrl.get(key);
        if (existing === undefined) {
          byUrl.set(key, candidate);
        }
      }
    });

    const deduped = [...byUrl.values()];
    const tokens = tokenize(query.q);

    let maxEngagement = 0;
    const logEngagement = new Map<string, number>();
    for (const item of deduped) {
      const e = Math.log10(1 + engagementMetric(item));
      logEngagement.set(item.url, e);
      if (e > maxEngagement) maxEngagement = e;
    }

    for (const item of deduped) {
      const raw = logEngagement.get(item.url) ?? 0;
      const engagementNorm = maxEngagement > 0 ? raw / maxEngagement : 0;
      item.score = Number(scoreItem(item, tokens, this.nowFn(), engagementNorm).toFixed(4));
    }

    deduped.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return a.url < b.url ? -1 : a.url > b.url ? 1 : 0;
    });

    const total = deduped.length;
    const limit = Math.max(1, query.limit);
    const items = deduped.slice(0, limit);

    return {
      query: query.q,
      sources: selected.map((s) => s.id),
      offline: this.offline,
      partial: failedSources.length > 0,
      failedSources,
      items,
      total,
      tookMs: Number((this.nowFn() - started).toFixed(3)),
      cache: this.cache.stats(),
    };
  }

  static digest(items: FeedItem[], query: SearchQuery, max = 10): string {
    const lines: string[] = [];
    lines.push(`# Feed digest: ${query.q}`);
    lines.push(`> ${items.length} item(s)${items.length > max ? ` (showing ${max})` : ""}`);
    lines.push("");
    for (const item of items.slice(0, max)) {
      lines.push(`## ${item.title}`);
      const meta: string[] = [`source: \`${item.source}\``, `score: \`${item.score}\``];
      if (item.publishedAt !== undefined) meta.push(item.publishedAt);
      lines.push(`- ${meta.join(" · ")}`);
      if (item.summary !== undefined) {
        const clipped = item.summary.length > 400 ? `${item.summary.slice(0, 400)}…` : item.summary;
        lines.push(`- ${clipped}`);
      }
      lines.push(`- <${item.url}>`);
      lines.push("");
    }
    return lines.join("\n");
  }
}
