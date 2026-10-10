import type { CallToolResult, ToolDefinition } from "../protocol/types.js";
import type { ToolDeps } from "./deps.js";
import { digestKey } from "./deps.js";

export const NET_SEARCH_TOOL: ToolDefinition = {
  name: "net_search",
  title: "Search open-source intelligence",
  description: "Cross-source query across Hacker News, GitHub, and arXiv with ranking, deduplication, and cache.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", minLength: 1, maxLength: 512 },
      sources: {
        type: "array",
        items: { type: "string", enum: ["hackernews", "github", "arxiv"] },
      },
      limit: { type: "integer", minimum: 1, maximum: 50, default: 10 },
      since: { type: "string", description: "ISO 8601 date cutoff" },
      tags: { type: "array", items: { type: "string" } },
      format: { type: "string", enum: ["json", "markdown"], default: "json" },
    },
    required: ["query"],
    additionalProperties: false,
  },
};

export const NET_DIGEST_TOOL: ToolDefinition = {
  name: "net_digest",
  title: "Digest a topic over a time window",
  description: "Generate a markdown digest of top discussions, repositories, and papers for a topic.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", minLength: 1, maxLength: 512 },
      sources: {
        type: "array",
        items: { type: "string", enum: ["hackernews", "github", "arxiv"] },
      },
      limit: { type: "integer", minimum: 1, maximum: 50, default: 10 },
      since: { type: "string" },
      tags: { type: "array", items: { type: "string" } },
    },
    required: ["query"],
    additionalProperties: false,
  },
};

export const NET_FETCH_TOOL: ToolDefinition = {
  name: "net_fetch",
  title: "Fetch and clean a single URL",
  description: "Fetches an HTTP URL and extracts clean readable text or markdown.",
  inputSchema: {
    type: "object",
    properties: {
      url: { type: "string", format: "uri" },
      clean: { type: "boolean", default: true },
    },
    required: ["url"],
    additionalProperties: false,
  },
};

export const NET_SOURCES_TOOL: ToolDefinition = {
  name: "net_sources",
  title: "List intelligence sources",
  description: "Inspect configured source adapters, homepage endpoints, and offline cache state.",
  inputSchema: {
    type: "object",
    properties: {},
    additionalProperties: false,
  },
};

export const NET_CACHE_TOOL: ToolDefinition = {
  name: "net_cache",
  title: "Inspect or purge the response cache",
  description: "Check cached item count and hit/miss statistics, or clear cached queries.",
  inputSchema: {
    type: "object",
    properties: {
      action: { type: "string", enum: ["inspect", "stats", "clear", "purge"], default: "inspect" },
    },
    additionalProperties: false,
  },
};

export function registerTools(registry: { registerTool: (def: ToolDefinition, handler: (args: Record<string, unknown>) => Promise<CallToolResult>) => void }, deps: ToolDeps): void {
  registry.registerTool(NET_SEARCH_TOOL, async (args) => {
    const query = String(args["query"] ?? "");
    const limit = typeof args["limit"] === "number" ? args["limit"] : 10;
    const since = typeof args["since"] === "string" ? args["since"] : undefined;
    const tags = Array.isArray(args["tags"]) ? (args["tags"] as string[]) : undefined;
    const sources = Array.isArray(args["sources"]) ? (args["sources"] as string[]) : undefined;

    const result = await deps.engine.search({ q: query, limit, since, tags }, sources);
    const text = JSON.stringify(result);

    return {
      content: [{ type: "text", text }],
      structuredContent: result as unknown as Record<string, unknown>,
    };
  });

  registry.registerTool(NET_DIGEST_TOOL, async (args) => {
    const query = String(args["query"] ?? "");
    const limit = typeof args["limit"] === "number" ? args["limit"] : 10;
    const since = typeof args["since"] === "string" ? args["since"] : undefined;
    const tags = Array.isArray(args["tags"]) ? (args["tags"] as string[]) : undefined;
    const sources = Array.isArray(args["sources"]) ? (args["sources"] as string[]) : undefined;

    const result = await deps.engine.search({ q: query, limit, since, tags }, sources);

    const lines: string[] = [
      `# NetIntel Digest: ${query}`,
      `Total items: ${result.total} across ${result.sources.join(", ")}`,
      "",
    ];

    for (const item of result.items) {
      lines.push(`- **[${item.source}]** [${item.title}](${item.url}) (score: ${item.score.toFixed(2)})`);
      if (item.summary) lines.push(`  > ${item.summary.slice(0, 200)}`);
    }

    const markdown = lines.join("\n");
    const dKey = digestKey(deps.cache, query, limit, since, tags);
    deps.cache.set(dKey, markdown);
    deps.onCacheTouch?.(dKey);

    return {
      content: [{ type: "text", text: markdown }],
      structuredContent: {
        query,
        total: result.total,
        digestKey: dKey,
        itemCount: result.items.length,
      },
    };
  });

  registry.registerTool(NET_FETCH_TOOL, async (args) => {
    const url = String(args["url"] ?? "");
    if (!url) {
      return {
        isError: true,
        content: [{ type: "text", text: "Missing URL parameter" }],
      };
    }

    const res = await deps.http.getText(url);
    if (!res.ok) {
      return {
        isError: true,
        content: [{ type: "text", text: `Fetch failed with status ${res.status}: ${res.error ?? "unknown error"}` }],
      };
    }

    const cleaned = res.text.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    return {
      content: [{ type: "text", text: cleaned }],
      structuredContent: { url, status: res.status, bytes: res.text.length },
    };
  });

  registry.registerTool(NET_SOURCES_TOOL, async () => {
    const sourceInfos = deps.sources.map((s) => ({
      id: s.id,
      label: s.label,
      homepage: s.homepage,
    }));

    return {
      content: [{ type: "text", text: JSON.stringify(sourceInfos, null, 2) }],
      structuredContent: { sources: sourceInfos, offline: deps.offline },
    };
  });

  registry.registerTool(NET_CACHE_TOOL, async (args) => {
    const action = String(args["action"] ?? "inspect");
    if (action === "clear" || action === "purge") {
      deps.cache.clear();
      return {
        content: [{ type: "text", text: "Cache cleared" }],
        structuredContent: { action: "cleared", stats: deps.cache.stats() },
      };
    }

    const stats = deps.cache.stats();
    return {
      content: [{ type: "text", text: JSON.stringify(stats, null, 2) }],
      structuredContent: { action: "inspected", stats },
    };
  });
}
