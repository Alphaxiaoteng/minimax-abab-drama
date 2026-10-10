import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { Registry } from "../src/protocol/registry.js";
import { McpServer } from "../src/protocol/server.js";

describe("Stdio Transport Protocol Flow", () => {
  it("processes requests via sink", async () => {
    const registry = new Registry();
    const cache = new ResponseCache();
    const server = new McpServer({
      registry,
      cache,
      serverInfo: { name: "test", version: "1.0.0" },
      instructions: "test",
    });

    const emitted: unknown[] = [];
    server.setSink({
      emit: (msg) => {
        emitted.push(msg);
      },
    });

    server.handleInput({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2025-06-18" },
    });
    server.handleInput({
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });

    await server.idle();
    assert.equal(emitted.length, 1);
    const resp = emitted[0] as { id: number; result: { protocolVersion: string } };
    assert.equal(resp.id, 1);
  });
});
