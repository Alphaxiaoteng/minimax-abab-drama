import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  INTERNAL_ERROR,
  INVALID_PARAMS,
  INVALID_REQUEST,
  METHOD_NOT_FOUND,
  PARSE_ERROR,
  invalidParams,
  invalidRequest,
  methodNotFound,
} from "../src/protocol/errors.js";

describe("JSON-RPC Protocol Errors", () => {
  it("defines standard error constants", () => {
    assert.equal(PARSE_ERROR, -32700);
    assert.equal(INVALID_REQUEST, -32600);
    assert.equal(METHOD_NOT_FOUND, -32601);
    assert.equal(INVALID_PARAMS, -32602);
    assert.equal(INTERNAL_ERROR, -32603);
  });

  it("creates structured JsonRpcError objects", () => {
    const err = invalidParams("Bad argument", { field: "limit" });
    assert.equal(err.code, -32602);
    assert.equal(err.message, "Bad argument");
    assert.deepEqual(err.data, { field: "limit" });

    const notFound = methodNotFound("Unknown");
    assert.equal(notFound.code, -32601);

    const reqErr = invalidRequest("Early message");
    assert.equal(reqErr.code, -32600);
  });
});
