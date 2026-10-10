import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Registry } from "../src/protocol/registry.js";

describe("Tool and Resource Registry", () => {
  it("registers and retrieves tools", () => {
    const reg = new Registry();
    reg.registerTool(
      { name: "t1", description: "d1", inputSchema: { type: "object" } },
      async () => ({ content: [{ type: "text", text: "ok" }] }),
    );

    assert.equal(reg.listTools().length, 1);
    assert.equal(reg.getTool("t1")?.def.name, "t1");
    assert.equal(reg.getTool("unknown"), undefined);
  });

  it("matches URI templates correctly", () => {
    const reg = new Registry();
    reg.registerResourceTemplate(
      { uriTemplate: "netintel://feed/{key}", name: "feed", description: "desc" },
      async () => ({ contents: [{ uri: "netintel://feed/test", text: "{}" }] }),
    );

    const match = reg.matchTemplateWithParams("netintel://feed/my-topic");
    assert.ok(match);
    assert.deepEqual(match.params, { key: "my-topic" });
  });
});
