import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { HttpClient } from "../src/net/http.js";
import { createSources } from "../src/net/sources/index.js";

const FIXTURE_DIR = path.resolve(process.cwd(), "fixtures", "feeds");

describe("Source Adapters (Offline Fixtures)", () => {
  const cache = new ResponseCache();
  const http = new HttpClient();
  const sources = createSources({
    http,
    cache,
    fixtureDir: FIXTURE_DIR,
    offline: true,
  });

  it("instantiates three unique source adapters", () => {
    assert.equal(sources.length, 3);
    const ids = sources.map((s) => s.id).sort();
    assert.deepEqual(ids, ["arxiv", "github", "hackernews"]);
  });

  it("queries hackernews adapter offline", async () => {
    const hn = sources.find((s) => s.id === "hackernews");
    assert.ok(hn);
    const items = await hn.search({ q: "mcp server", limit: 5 });
    assert.ok(items.length > 0);
    assert.ok(items[0]?.title);
    assert.ok(items[0]?.url);
  });

  it("queries github adapter offline", async () => {
    const gh = sources.find((s) => s.id === "github");
    assert.ok(gh);
    const items = await gh.search({ q: "mcp server", limit: 5 });
    assert.ok(items.length > 0);
    assert.ok(items[0]?.title);
    assert.ok(items[0]?.url);
  });

  it("queries arxiv adapter offline", async () => {
    const arx = sources.find((s) => s.id === "arxiv");
    assert.ok(arx);
    const items = await arx.search({ q: "mcp server", limit: 5 });
    assert.ok(items.length > 0);
    assert.ok(items[0]?.title);
    assert.ok(items[0]?.url);
  });
});
