import type { FetchLike, FetchResponse } from "./types.js";

export interface HttpClientOptions {
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  retries?: number;
  backoffMs?: number;
  userAgent?: string;
}

export interface HttpResult {
  ok: boolean;
  status: number;
  text: string;
  error?: string;
}

const DEFAULT_TIMEOUT_MS = 8000;
const DEFAULT_RETRIES = 2;
const DEFAULT_BACKOFF_MS = 250;
const MAX_BACKOFF_MS = 2000;
const DEFAULT_USER_AGENT = "netintel-mcp/0.1.0 (+https://github.com/)";

/**
 * Never throws for network/HTTP/timeout errors: failures collapse into
 * `{ ok: false, status: 0 | code, text: "", error }` so the feed layer can
 * isolate per-source degradation instead of aborting the whole request.
 */
export class HttpClient {
  private readonly fetch: FetchLike;
  private readonly timeoutMs: number;
  private readonly retries: number;
  private readonly backoffMs: number;
  private readonly userAgent: string;

  constructor(opts: HttpClientOptions = {}) {
    this.fetch = opts.fetchImpl ?? defaultFetch;
    this.timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.retries = opts.retries ?? DEFAULT_RETRIES;
    this.backoffMs = opts.backoffMs ?? DEFAULT_BACKOFF_MS;
    this.userAgent = opts.userAgent ?? DEFAULT_USER_AGENT;
  }

  async getText(
    url: string,
    init?: { signal?: AbortSignal; headers?: Record<string, string> },
  ): Promise<HttpResult> {
    const headers: Record<string, string> = {
      "user-agent": this.userAgent,
      accept: "*/*",
      ...(init?.headers ?? {}),
    };

    let attempt = 0;
    let delay = this.backoffMs;
    let lastStatus = 0;

    for (;;) {
      if (init?.signal?.aborted === true) {
        return { ok: false, status: lastStatus, text: "", error: "Aborted" };
      }
      const { signal: timeoutSignal, clear } = startTimeout(this.timeoutMs);
      const combined = combineSignals(init?.signal, timeoutSignal);

      try {
        const res = await this.fetch(url, {
          headers,
          signal: combined,
          timeoutMs: this.timeoutMs,
        });
        clear();
        if (res.status >= 500 || res.status === 429) {
          lastStatus = res.status;
          const error = `HTTP ${res.status}`;
          if (attempt < this.retries) {
            await sleep(delay);
            delay = Math.min(delay * 2, MAX_BACKOFF_MS);
            attempt += 1;
            continue;
          }
          return { ok: false, status: res.status, text: "", error };
        }
        if (!res.ok) {
          return { ok: false, status: res.status, text: "", error: `HTTP ${res.status}` };
        }
        return { ok: true, status: res.status, text: await res.text() };
      } catch (err) {
        clear();
        if (Boolean(init?.signal?.aborted)) {
          return { ok: false, status: 0, text: "", error: "Aborted" };
        }
        lastStatus = 0;
        const error = err instanceof Error ? err.message : String(err);
        if (attempt < this.retries) {
          await sleep(delay);
          delay = Math.min(delay * 2, MAX_BACKOFF_MS);
          attempt += 1;
          continue;
        }
        return { ok: false, status: 0, text: "", error };
      }
    }
  }
}

interface TimeoutHandle {
  signal: AbortSignal;
  clear(): void;
}

function startTimeout(ms: number): TimeoutHandle {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), ms);
  return {
    signal: controller.signal,
    clear() {
      clearTimeout(timer);
    },
  };
}

function combineSignals(
  caller: AbortSignal | undefined,
  timeout: AbortSignal,
): AbortSignal {
  if (caller === undefined) return timeout;
  if (caller.aborted) return caller;
  if (timeout.aborted) return timeout;
  const merged = new AbortController();
  caller.addEventListener("abort", () => merged.abort(caller.reason), { once: true });
  timeout.addEventListener("abort", () => merged.abort(timeout.reason), { once: true });
  return merged.signal;
}

function defaultFetch(url: string, init?: { headers?: Record<string, string>; signal?: AbortSignal }): Promise<FetchResponse> {
  const fetchFn = globalThis.fetch;
  if (typeof fetchFn !== "function") {
    return Promise.reject(new Error("global fetch unavailable; pass fetchImpl to HttpClient"));
  }
  return fetchFn(url, { headers: init?.headers, signal: init?.signal }).then((res) => ({
    status: res.status,
    ok: res.ok,
    headers: Object.fromEntries(res.headers.entries()),
    text: () => res.text(),
  }));
}

function sleep(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}
