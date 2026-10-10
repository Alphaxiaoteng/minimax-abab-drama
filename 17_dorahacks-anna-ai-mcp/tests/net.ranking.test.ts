import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { tokenize } from "../src/net/feeds.js";

describe("Ranking and Tokenization", () => {
  it("tokenizes alphanumeric words in lowercase", () => {
    const tokens = tokenize("Hello, World! MCP-Search 2026");
    assert.deepEqual(tokens, ["hello", "world", "mcp", "search", "2026"]);
  });

  it("deduplicates repeated tokens while preserving order", () => {
    const tokens = tokenize("apple banana apple cherry banana");
    assert.deepEqual(tokens, ["apple", "banana", "cherry"]);
  });

  it("handles empty or special character strings gracefully", () => {
    assert.deepEqual(tokenize(""), []);
    assert.deepEqual(tokenize("--- @@@ ###"), []);
  });
});
