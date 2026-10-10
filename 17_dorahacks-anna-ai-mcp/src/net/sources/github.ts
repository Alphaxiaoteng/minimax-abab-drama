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

interface GhItem {
  id?: unknown;
  full_name?: unknown;
  html_url?: unknown;
  description?: unknown;
  owner?: unknown;
  created_at?: unknown;
  stargazers_count?: unknown;
  topics?: unknown;
}

const GITHUB_ENDPOINT = "https://api.github.com/search/repositories";

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

function ownerLogin(item: GhItem): string | undefined {
  const owner = item.owner;
  if (typeof owner === "object" && owner !== null) {
    return toStr((owner as { login?: unknown }).login);
  }
  return undefined;
}

function mapItem(raw: GhItem): RawItem | undefined {
  const numericId = toNum(raw.id);
  const fullName = toStr(raw.full_name);
  const url = toStr(raw.html_url);
  if (fullName === undefined || url === undefined) return undefined;
  const item: RawItem = { id: String(numericId ?? fullName), title: fullName, url };
  const author = ownerLogin(raw);
  const summary = toStr(raw.description);
  const stars = toNum(raw.stargazers_count);
  if (author !== undefined) item.author = author;
  if (summary !== undefined) item.summary = summary;
  if (Array.isArray(raw.topics)) {
    const tags = raw.topics.filter((t): t is string => typeof t === "string");
    if (tags.length > 0) item.tags = tags;
  }
  if (stars !== undefined) item.metrics = { stars };
  const published = toIso(raw.created_at);
  if (published !== undefined) item.publishedAt = published;
  return item;
}

export class GitHubSource implements SourceAdapter {
  readonly id = "github" as const;
  readonly label = "GitHub";
  readonly homepage = "https://github.com/";

  private readonly http: HttpClient;
  private readonly cache: ResponseCacheLike;
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
        return fromFixture(this.fixtureDir, this.id, key, extract);
      }
      const res = await this.http.getText(this.buildUrl(query), {
        headers: { accept: "application/vnd.github+json" },
      });
      // GitHub returns 403 on rate limit — surface it as an empty, non-cacheable
      // result rather than a hard failure (the feed layer reports `partial`).
      if (!res.ok) {
        return { items: [], cacheable: false };
      }
      return safeParse(this.id, () => extract(res.text));
    });
  }

  private buildUrl(query: SearchQuery): string {
    const params = new URLSearchParams();
    params.set("q", query.q);
    if (query.since !== undefined) {
      const date = query.since.slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}$/.test(date)) params.append("q", `created:>=${date}`);
    }
    params.set("sort", "stars");
    params.set("order", "desc");
    params.set("per_page", String(clampLimit(query.limit)));
    return `${GITHUB_ENDPOINT}?${params.toString()}`;
  }
}

function extract(text: string): RawItem[] {
  const parsed = JSON.parse(text) as { items?: unknown };
  const items = Array.isArray(parsed.items) ? parsed.items : [];
  const out: RawItem[] = [];
  for (const raw of items) {
    const mapped = mapItem(raw as GhItem);
    if (mapped !== undefined) out.push(mapped);
  }
  return out;
}

import type { ResponseCache as ResponseCacheLike } from "../cache.js";
import { readFixture as _unusedReadFixture } from "./shared.js";
void _unusedReadFixture;

interface FixtureLoader {
  (fixtureDir: string, sourceId: string, key: string, parse: (text: string) => RawItem[]): {
    items: RawItem[];
    cacheable: boolean;
  };
}

/** Shared fixture reader used by GitHub + arXiv adapters. */
export const fromFixture: FixtureLoader = (fixtureDir, sourceId, key, parse) => {
  const text = readFixture(fixtureDir, sourceId, key);
  if (text === undefined) {
    return { items: [], cacheable: true };
  }
  return safeParse(sourceId, () => parse(text));
};
