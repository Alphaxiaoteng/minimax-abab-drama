import type { HttpClient } from "../http.js";
import type { RawItem, SearchQuery, SourceAdapter } from "../types.js";
import { findAll, parseXml, textOf } from "../xml.js";
import {
  clampLimit,
  queryCacheKey,
  readFixture,
  readThrough,
  safeParse,
  type SourceOptions,
} from "./shared.js";

const ARXIV_ENDPOINT = "http://export.arxiv.org/api/query";

function cleanWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function parseAtomFeed(xmlText: string, limit: number): RawItem[] {
  const root = parseXml(xmlText);
  const entries = findAll(root, "entry");
  const items: RawItem[] = [];

  for (const entry of entries) {
    if (items.length >= limit) break;

    const idNode = entry.children.find((c) => c.name === "id");
    const rawId = textOf(idNode).trim();
    if (!rawId) continue;

    const titleNode = entry.children.find((c) => c.name === "title");
    const rawTitle = cleanWhitespace(textOf(titleNode));
    if (!rawTitle) continue;

    const publishedNode = entry.children.find((c) => c.name === "published");
    const publishedAt = textOf(publishedNode).trim() || undefined;

    const summaryNode = entry.children.find((c) => c.name === "summary");
    const summary = cleanWhitespace(textOf(summaryNode)) || undefined;

    const authorNode = entry.children.find((c) => c.name === "author");
    let author: string | undefined;
    if (authorNode) {
      const nameNode = authorNode.children.find((c) => c.name === "name");
      author = textOf(nameNode).trim() || undefined;
    }

    let url: string | undefined;
    const links = entry.children.filter((c) => c.name === "link");
    const alternate = links.find((l) => l.attrs["rel"] === "alternate" || l.attrs["type"] === "text/html");
    if (alternate?.attrs["href"]) {
      url = alternate.attrs["href"];
    } else {
      url = rawId;
    }

    const categories = entry.children.filter((c) => c.name === "category");
    const tags = categories
      .map((c) => c.attrs["term"])
      .filter((t): t is string => typeof t === "string" && t.length > 0);

    const item: RawItem = {
      id: rawId,
      title: rawTitle,
      url,
    };
    if (author) item.author = author;
    if (publishedAt) item.publishedAt = publishedAt;
    if (summary) item.summary = summary;
    if (tags.length > 0) item.tags = tags;

    items.push(item);
  }

  return items;
}

export class ArxivSourceAdapter implements SourceAdapter {
  readonly id = "arxiv" as const;
  readonly label = "arXiv";
  readonly homepage = "https://arxiv.org";

  private readonly http: HttpClient;
  private readonly cache: SourceOptions["cache"];
  private readonly fixtureDir: string;
  private readonly offline: boolean;

  constructor(opts: SourceOptions) {
    this.http = opts.http;
    this.cache = opts.cache;
    this.fixtureDir = opts.fixtureDir;
    this.offline = opts.offline;
  }

  async search(query: SearchQuery): Promise<RawItem[]> {
    const limit = clampLimit(query.limit);
    const key = queryCacheKey(this.id, { ...query, limit });

    return readThrough(this.cache, key, async () => {
      if (this.offline) {
        const text = readFixture(this.fixtureDir, this.id, key);
        if (!text) return { items: [], cacheable: false };
        return safeParse(this.id, () => {
          let xmlStr = text;
          try {
            const parsed = JSON.parse(text) as { xml?: string };
            if (typeof parsed?.xml === "string") {
              xmlStr = parsed.xml;
            }
          } catch {
            // raw XML
          }
          return parseAtomFeed(xmlStr, limit);
        });
      }

      const q = encodeURIComponent(`all:${query.q}`);
      const url = `${ARXIV_ENDPOINT}?search_query=${q}&max_results=${limit}&sortBy=submittedDate&sortOrder=descending`;
      const res = await this.http.getText(url);
      if (!res.ok) {
        const fallbackText = readFixture(this.fixtureDir, this.id, key);
        if (fallbackText) {
          return safeParse(this.id, () => {
            const parsed = JSON.parse(fallbackText) as { xml?: string };
            return parseAtomFeed(parsed.xml ?? fallbackText, limit);
          });
        }
        return { items: [], cacheable: false };
      }

      return safeParse(this.id, () => parseAtomFeed(res.text, limit));
    });
  }
}
