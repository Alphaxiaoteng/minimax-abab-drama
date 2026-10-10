import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { paginate } from "../src/protocol/pagination.js";

describe("Protocol Pagination", () => {
  const items = ["a", "b", "c", "d", "e"];

  it("returns full list when count <= pageSize", () => {
    const p = paginate(items, undefined, 10);
    assert.deepEqual(p.page, items);
    assert.equal(p.nextCursor, undefined);
  });

  it("splits list across pages with cursor", () => {
    const page1 = paginate(items, undefined, 2);
    assert.deepEqual(page1.page, ["a", "b"]);
    assert.ok(page1.nextCursor);

    const page2 = paginate(items, page1.nextCursor, 2);
    assert.deepEqual(page2.page, ["c", "d"]);
    assert.ok(page2.nextCursor);

    const page3 = paginate(items, page2.nextCursor, 2);
    assert.deepEqual(page3.page, ["e"]);
    assert.equal(page3.nextCursor, undefined);
  });
});
