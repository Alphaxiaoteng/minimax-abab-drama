import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { Registry } from "../src/protocol/registry.js";
import { McpServer } from "../src/protocol/server.js";

describe("Protocol Lifecycle", () => {
  it("progresses through lifecycle phases", () => {
    const registry = new Registry();
    const cache = new ResponseCache();
    const server = new McpServer({
      registry,
      cache,
      serverInfo: { name: "test-server", version: "1.0.0" },
      instructions: "lifecycle test",
    });

    assert.equal(server.phase, "await-initialize");
    assert.equal(server.isReady, false);

    server.handleInput({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2025-06-18" },
    });
    assert.equal(server.phase, "await-initialized");

    server.handleInput({
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });
    assert.equal(server.phase, "ready");
    assert.equal(server.isReady, true);

    server.close();
    assert.equal(server.phase, "closed");
    assert.equal(server.isReady, false);
  });
});
