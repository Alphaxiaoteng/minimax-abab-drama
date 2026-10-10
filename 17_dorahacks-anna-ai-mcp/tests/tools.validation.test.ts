import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { applyDefaults, validateAgainstSchema } from "../src/tools/validate.js";

describe("Tool Schema Validation", () => {
  const schema = {
    type: "object",
    properties: {
      query: { type: "string", minLength: 1 },
      limit: { type: "integer", default: 10 },
      tags: { type: "array", items: { type: "string" } },
    },
    required: ["query"],
    additionalProperties: false,
  };

  it("applies default values for missing fields", () => {
    const args = applyDefaults(schema, { query: "test" });
    assert.equal(args["limit"], 10);
  });

  it("validates compliant arguments with no errors", () => {
    const errors = validateAgainstSchema(schema, { query: "test", limit: 5 });
    assert.equal(errors.length, 0);
  });

  it("reports errors for missing required properties", () => {
    const errors = validateAgainstSchema(schema, { limit: 5 });
    assert.ok(errors.length > 0);
    assert.ok(errors.some((e) => e.path.includes("query")));
  });

  it("reports errors for undeclared additional properties", () => {
    const errors = validateAgainstSchema(schema, { query: "test", extra: "bad" });
    assert.ok(errors.length > 0);
  });
});
