import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { FeedEngine } from "../src/net/feeds.js";
import { HttpClient } from "../src/net/http.js";
import { BRIEF_TOPIC_PROMPT, registerPrompts } from "../src/prompts/index.js";
import { Registry } from "../src/protocol/registry.js";
import type { ServerContext } from "../src/protocol/types.js";
import { CATALOG_RESOURCE, FEED_TEMPLATE, registerResources } from "../src/resources/index.js";
import { SubscriptionHub } from "../src/resources/subscriptions.js";
import type { ResourceDeps } from "../src/tools/deps.js";

describe("Resources and Prompts Registration", () => {
  const cache = new ResponseCache();
  const http = new HttpClient();
  const engine = new FeedEngine({ sources: [], cache });
  const subscriptions = new SubscriptionHub();
  const registry = new Registry();

  const deps: ResourceDeps = {
    engine,
    sources: [],
    cache,
    http,
    offline: true,
    config: {
      transport: "stdio",
      port: 3000,
      host: "127.0.0.1",
      offline: true,
      fixtureDir: "",
      cacheTtlMs: 300000,
      cacheMax: 256,
      timeoutMs: 5000,
      logLevel: "info",
      allowAnyOrigin: false,
    },
    subscriptions,
  };

  registerResources(registry, deps);
  registerPrompts(registry, deps);

  it("registers catalog resource and feed template", () => {
    assert.ok(registry.getResource(CATALOG_RESOURCE.uri));
    assert.ok(registry.matchTemplate("netintel://feed/abc"));
  });

  it("registers brief_topic prompt", () => {
    assert.ok(registry.getPrompt(BRIEF_TOPIC_PROMPT.name));
  });

  it("reads catalog resource successfully", async () => {
    const handler = registry.getResource(CATALOG_RESOURCE.uri);
    assert.ok(handler);
    const mockCtx: ServerContext = {
      notify: () => {},
      progress: () => {},
      log: () => {},
      signal: new AbortController().signal,
      clientCapabilities: {},
      cache,
    };
    const res = await handler.handler(CATALOG_RESOURCE.uri, mockCtx);
    assert.ok(res.contents.length > 0);
    const parsed = JSON.parse(res.contents[0]?.text ?? "{}") as { uri: string };
    assert.equal(parsed.uri, CATALOG_RESOURCE.uri);
  });
});
