import type { ResponseCache } from "../cache.js";
import type { HttpClient } from "../http.js";
import type { RawItem, SearchQuery, SourceAdapter } from "../types.js";
import {
  clampLimit,
  queryCacheKey,
  readFixture,
  readThrough,
  safeParse,
  type SourceOptions,
} from "./shared.js";

interface HnHit {
  objectID?: unknown;
  title?: unknown;
  url?: unknown;
  author?: unknown;
  created_at?: unknown;
  story_text?: unknown;
  points?: unknown;
  num_comments?: unknown;
  _tags?: unknown;
}

const HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date";

function toStr(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function toNum(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function toIso(v: unknown): string | undefined {
  const s = toStr(v);
  if (s === undefined) return undefined;
  const ts = Date.parse(s);
  return Number.isNaN(ts) ? undefined : new Date(ts).toISOString();
}

function mapHit(hit: HnHit): RawItem | undefined {
  const id = toStr(hit.objectID);
  const title = toStr(hit.title);
  if (id === undefined || title === undefined) return undefined;
  // Ask HN posts have no external url; synthesise the item page so dedupe has a key.
  const url = toStr(hit.url) ?? `https://news.ycombinator.com/item?id=${id}`;
  const metrics: Record<string, number> = {};
  const points = toNum(hit.points);
  const comments = toNum(hit.num_comments);
  if (points !== undefined) metrics["score"] = points;
  if (comments !== undefined) metrics["comments"] = comments;
  const tags = Array.isArray(hit._tags)
    ? hit._tags.filter((t): t is string => typeof t === "string")
    : undefined;
  const item: RawItem = { id, title, url, publishedAt: toIso(hit.created_at) };
  const author = toStr(hit.author);
  const summary = toStr(hit.story_text);
  if (author !== undefined) item.author = author;
  if (summary !== undefined) item.summary = summary;
  if (tags !== undefined && tags.length > 0) item.tags = tags;
  if (Object.keys(metrics).length > 0) item.metrics = metrics;
  return item;
}

export class HackerNewsSource implements SourceAdapter {
  readonly id = "hackernews" as const;
  readonly label = "Hacker News";
  readonly homepage = "https://news.ycombinator.com/";

  private readonly http: HttpClient;
  private readonly cache: ResponseCache;
  private readonly fixtureDir: string;
  private readonly offline: boolean;

  constructor(opts: SourceOptions) {
    this.http = opts.http;
    this.cache = opts.cache;
    this.fixtureDir = opts.fixtureDir;
    this.offline = opts.offline;
  }

  async search(query: SearchQuery): Promise<RawItem[]> {
    const key = queryCacheKey(this.id, query);
    return readThrough(this.cache, key, async () => {
      if (this.offline) {
        return this.fromFixture(key);
      }
      const url = this.buildUrl(query);
      const res = await this.http.getText(url);
      if (!res.ok) {
        return { items: [], cacheable: false };
      }
      return safeParse(this.id, () => {
        const parsed = JSON.parse(res.text) as { hits?: unknown };
        const hits = Array.isArray(parsed.hits) ? parsed.hits : [];
        const items: RawItem[] = [];
        for (const hit of hits) {
          const item = mapHit(hit as HnHit);
          if (item !== undefined) items.push(item);
        }
        return items;
      });
    });
  }

  private fromFixture(key: string): { items: RawItem[]; cacheable: boolean } {
    const text = readFixture(this.fixtureDir, this.id, key);
    if (text === undefined) {
      return { items: [], cacheable: true };
    }
    return safeParse(this.id, () => {
      const parsed = JSON.parse(text) as { hits?: unknown };
      const hits = Array.isArray(parsed.hits) ? parsed.hits : [];
      const items: RawItem[] = [];
      for (const hit of hits) {
        const item = mapHit(hit as HnHit);
        if (item !== undefined) items.push(item);
      }
      return items;
    });
  }

  private buildUrl(query: SearchQuery): string {
    const params = new URLSearchParams();
    params.set("query", query.q);
    params.set("tags", "story");
    params.set("hitsPerPage", String(clampLimit(query.limit)));
    if (query.since !== undefined) {
      const ts = Date.parse(query.since);
      if (!Number.isNaN(ts)) params.set("numericFilters", `created_at_i>${Math.floor(ts / 1000)}`);
    }
    return `${HN_ENDPOINT}?${params.toString()}`;
  }
}
