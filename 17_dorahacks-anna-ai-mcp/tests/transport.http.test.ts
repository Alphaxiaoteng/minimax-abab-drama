import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { Registry } from "../src/protocol/registry.js";
import { McpServer } from "../src/protocol/server.js";
import { runHttpTransport } from "../src/transports/http.js";

describe("HTTP Transport", () => {
  it("starts HTTP server and handles POST request", async () => {
    const registry = new Registry();
    const cache = new ResponseCache();
    const server = new McpServer({
      registry,
      cache,
      serverInfo: { name: "test-http", version: "1.0.0" },
      instructions: "test",
    });

    const httpServer = runHttpTransport(server, 0);
    const addr = httpServer.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;

    try {
      const res = await fetch(`http://127.0.0.1:${port}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "initialize",
          params: { protocolVersion: "2025-06-18" },
        }),
      });

      assert.equal(res.status, 200);
      const data = (await res.json()) as { id: number; result: { protocolVersion: string } };
      assert.equal(data.id, 1);
      assert.equal(data.result.protocolVersion, "2025-06-18");
    } finally {
      httpServer.close();
    }
  });
});
