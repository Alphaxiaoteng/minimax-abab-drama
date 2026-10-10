import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { failure, notification, success } from "../src/protocol/jsonrpc.js";
import { decodeEnvelope } from "../src/protocol/validate.js";

describe("JSON-RPC Envelope and Helpers", () => {
  it("formats success response properly", () => {
    const s = success(42, { ok: true });
    assert.equal(s.jsonrpc, "2.0");
    assert.equal(s.id, 42);
    assert.deepEqual(s.result, { ok: true });
  });

  it("formats failure response properly", () => {
    const f = failure(42, -32600, "Invalid Request");
    assert.equal(f.jsonrpc, "2.0");
    assert.equal(f.id, 42);
    assert.equal(f.error.code, -32600);
    assert.equal(f.error.message, "Invalid Request");
  });

  it("formats notification message without id", () => {
    const n = notification("notifications/test", { active: true });
    assert.equal(n.jsonrpc, "2.0");
    assert.equal("id" in n, false);
    assert.equal(n.method, "notifications/test");
  });

  it("rejects non-object envelope", () => {
    const dec = decodeEnvelope("not-json");
    assert.equal(dec.kind, "invalid");
  });
});
