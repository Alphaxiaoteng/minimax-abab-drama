import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { decodeEnvelope } from "../src/protocol/validate.js";

describe("JSON-RPC Envelope Fuzzing", () => {
  const fuzzInputs: unknown[] = [
    null,
    undefined,
    12345,
    true,
    false,
    "",
    "   ",
    [],
    [1, 2, 3],
    {},
    { jsonrpc: "1.0" },
    { jsonrpc: 2.0 },
    { jsonrpc: "2.0" },
    { jsonrpc: "2.0", method: 123 },
    { jsonrpc: "2.0", id: {} },
    { jsonrpc: "2.0", id: [] },
    { method: "ping" },
  ];

  it("handles fuzz payloads without throwing uncaught exceptions", () => {
    for (const input of fuzzInputs) {
      assert.doesNotThrow(() => {
        const decoded = decodeEnvelope(input);
        assert.ok(decoded.kind === "invalid" || decoded.kind === "ignore" || decoded.kind === "batch");
      });
    }
  });
});
