import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ResponseCache } from "../src/net/cache.js";
import { Registry } from "../src/protocol/registry.js";
import { McpServer } from "../src/protocol/server.js";
import { decodeEnvelope, isRecord } from "../src/protocol/validate.js";

describe("Protocol Core", () => {
  it("validates records correctly", () => {
    assert.equal(isRecord({}), true);
    assert.equal(isRecord(null), false);
    assert.equal(isRecord([]), false);
    assert.equal(isRecord("str"), false);
  });

  it("decodes JSON-RPC envelopes", () => {
    const validReq = decodeEnvelope({ jsonrpc: "2.0", id: 1, method: "ping" });
    assert.equal(validReq.kind, "request");

    const validNotif = decodeEnvelope({ jsonrpc: "2.0", method: "notifications/initialized" });
    assert.equal(validNotif.kind, "notification");

    const invalid = decodeEnvelope("not-an-object");
    assert.equal(invalid.kind, "invalid");
  });

  it("handles initialize and protocol version negotiation", async () => {
    const registry = new Registry();
    const cache = new ResponseCache();
    const server = new McpServer({
      registry,
      cache,
      serverInfo: { name: "test-server", version: "1.0.0" },
      instructions: "test instructions",
    });

    const initMsg = {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "test-client", version: "1.0.0" },
      },
    };

    let response: unknown = null;
    server.setSink({
      emit: (msg) => {
        response = msg;
      },
    });

    server.handleInput(initMsg);
    await server.idle();
    assert.ok(response);
    const respObj = response as { jsonrpc: string; id: number; result: { protocolVersion: string } };
    assert.equal(respObj.id, 1);
    assert.equal(respObj.result.protocolVersion, "2025-06-18");
  });
});
