import { resolve } from "node:path";
import { loadConfig } from "./config.js";
import { ResponseCache } from "./net/cache.js";
import { FeedEngine } from "./net/feeds.js";
import { HttpClient } from "./net/http.js";
import { createSources } from "./net/sources/index.js";
import { registerPrompts } from "./prompts/index.js";
import { Registry } from "./protocol/registry.js";
import { McpServer } from "./protocol/server.js";
import { registerResources } from "./resources/index.js";
import { SubscriptionHub } from "./resources/subscriptions.js";
import type { ResourceDeps, ToolDeps } from "./tools/deps.js";
import { registerTools } from "./tools/index.js";
import { runHttpTransport, runStdioTransport } from "./transports/index.js";
import { VERSION } from "./version.js";

function parseArgs(args: string[]): {
  offline: boolean;
  fixtureDir: string;
  transport: "stdio" | "http";
  port: number;
} {
  let offline = false;
  let fixtureDir = resolve(process.cwd(), "fixtures", "feeds");
  let transport: "stdio" | "http" = "stdio";
  let port = 3000;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--offline") {
      offline = true;
    } else if (arg === "--fixture-dir" && i + 1 < args.length) {
      fixtureDir = resolve(process.cwd(), args[++i]!);
    } else if (arg === "--transport" && i + 1 < args.length) {
      const t = args[++i];
      if (t === "http" || t === "stdio") transport = t;
    } else if (arg === "--port" && i + 1 < args.length) {
      port = Number.parseInt(args[++i]!, 10) || 3000;
    }
  }

  return { offline, fixtureDir, transport, port };
}

export function main(): void {
  const opts = parseArgs(process.argv.slice(2));
  const config = loadConfig(process.env, process.argv.slice(2));
  if (opts.offline) config.offline = true;

  const cache = new ResponseCache({ ttlMs: config.cacheTtlMs, maxEntries: config.cacheMax });
  const http = new HttpClient();
  const sources = createSources({
    http,
    cache,
    fixtureDir: opts.fixtureDir,
    offline: opts.offline || config.offline,
  });

  const engine = new FeedEngine({
    sources,
    cache,
    offline: opts.offline || config.offline,
  });

  const subscriptions = new SubscriptionHub();
  const registry = new Registry();

  let server!: McpServer;

  const toolDeps: ToolDeps = {
    engine,
    sources,
    cache,
    http,
    offline: opts.offline || config.offline,
    config,
    onCacheTouch: (key: string) => {
      const toNotify = subscriptions.notifyCacheKey(key);
      for (const item of toNotify) {
        server.notifyResourceUpdated(item.uri);
      }
    },
  };

  const resourceDeps: ResourceDeps = {
    ...toolDeps,
    subscriptions,
  };

  registerTools(registry, toolDeps);
  registerResources(registry, resourceDeps);
  registerPrompts(registry, toolDeps);

  registry.setCompletions(async (argName, value) => {
    if (argName === "sources") {
      const all = ["hackernews", "github", "arxiv"];
      return { values: all.filter((s) => s.startsWith(value)) };
    }
    return { values: [] };
  });

  server = new McpServer({
    registry,
    cache,
    serverInfo: {
      name: "netintel-mcp",
      title: "NetIntel Open Source Intelligence MCP Server",
      version: VERSION,
    },
    instructions: "NetIntel delivers open-source intelligence across Hacker News, GitHub, and arXiv.",
  });

  if (opts.transport === "http") {
    runHttpTransport(server, opts.port);
  } else {
    runStdioTransport(server);
  }
}

if (process.argv[1]?.endsWith("cli.js") || process.argv[1]?.endsWith("cli.ts")) {
  main();
}
