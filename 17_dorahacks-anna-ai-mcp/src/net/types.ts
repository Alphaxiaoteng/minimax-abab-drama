export interface RawItem {
  id: string;
  title: string;
  url: string;
  author?: string;
  publishedAt?: string;
  summary?: string;
  tags?: string[];
  metrics?: Record<string, number>;
}

export interface SearchQuery {
  q: string;
  limit: number;
  since?: string;
  tags?: string[];
}

export interface SourceAdapter {
  readonly id: "hackernews" | "github" | "arxiv";
  readonly label: string;
  readonly homepage: string;
  /** Must never throw for network/HTTP errors — return the empty array and let the caller log. */
  search(query: SearchQuery): Promise<RawItem[]>;
}

export interface FetchResponse {
  status: number;
  ok: boolean;
  headers: Record<string, string>;
  text(): Promise<string>;
}

export interface FetchLike {
  (
    url: string,
    init?: { headers?: Record<string, string>; signal?: AbortSignal; timeoutMs?: number },
  ): Promise<FetchResponse>;
}
