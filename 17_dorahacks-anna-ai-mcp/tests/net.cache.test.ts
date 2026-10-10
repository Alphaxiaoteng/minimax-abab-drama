import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";

describe("ResponseCache", () => {
  it("stores and retrieves values within TTL", () => {
    let now = 1000;
    const cache = new ResponseCache({ ttlMs: 5000, now: () => now });

    cache.set("k1", { foo: "bar" });
    const val = cache.get("k1");
    assert.deepEqual(val, { foo: "bar" });

    const stats = cache.stats();
    assert.equal(stats.hits, 1);
    assert.equal(stats.misses, 0);
    assert.equal(stats.sets, 1);
  });

  it("expires entries past TTL", () => {
    let now = 1000;
    const cache = new ResponseCache({ ttlMs: 2000, now: () => now });

    cache.set("k1", "val");
    now += 3000;

    const val = cache.get("k1");
    assert.equal(val, undefined);

    const stats = cache.stats();
    assert.equal(stats.misses, 1);
  });

  it("evicts oldest entry when maxEntries is exceeded", () => {
    const cache = new ResponseCache({ maxEntries: 2 });
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("c", 3);

    assert.equal(cache.get("a"), undefined);
    assert.equal(cache.get("b"), 2);
    assert.equal(cache.get("c"), 3);
  });

  it("clears all entries", () => {
    const cache = new ResponseCache();
    cache.set("a", 1);
    cache.clear();
    assert.equal(cache.get("a"), undefined);
    assert.equal(cache.stats().entries, 0);
  });
});
