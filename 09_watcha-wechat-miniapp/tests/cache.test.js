'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createCache } = require('../src/utils/cache.js');

function makeMemStorage() {
  const m = new Map();
  return {
    getSync: (k) => (m.has(k) ? m.get(k) : null),
    setSync: (k, v) => m.set(k, v),
    removeSync: (k) => m.delete(k)
  };
}

function rec(id, score, ts, over) {
  return Object.assign({
    id: id, scene: 'quickread', title: id, summary: '', raw: id, ts: ts, hit: 0, score: score, tags: [], meta: {}
  }, over || {});
}

test('cache：storage 必须实现 getSync/setSync，否则抛错', () => {
  assert.throws(() => createCache({ storage: {} }), /storage/);
});

test('cache：put 后 list/get 命中，缺省字段被规范化', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't1', limit: 10 });
  cache.put({ id: 'x', raw: 'content', score: 5, ts: 1000 });
  const got = cache.get('x');
  assert.ok(got);
  assert.equal(got.scene, 'quickread');
  assert.deepEqual(got.tags, []);
});

test('cache：rank 按 score 降序、同分按 ts 降序', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't2', limit: 10 });
  cache.put(rec('a', 10, 1));
  cache.put(rec('b', 20, 2));
  cache.put(rec('c', 10, 99));
  assert.deepEqual(cache.rank().map((r) => r.id), ['b', 'c', 'a']);
});

test('cache：超出 limit 被裁剪', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't3', limit: 3 });
  for (let i = 0; i < 5; i++) cache.put(rec('id' + i, i, i));
  assert.equal(cache.list().length, 3);
});

test('cache：search 大小写不敏感、空关键词返回全部', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't4', limit: 10 });
  cache.put(rec('x', 1, 1, { title: 'FooBar' }));
  cache.put(rec('y', 1, 2, { title: 'other' }));
  assert.deepEqual(cache.search('foo').map((r) => r.id), ['x']);
  assert.equal(cache.search('').length, 2);
});

test('cache：remove 命中返回 true、未命中 false', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't5', limit: 10 });
  cache.put(rec('a', 1, 1));
  assert.equal(cache.remove('a'), true);
  assert.equal(cache.remove('a'), false);
});

test('cache：同 id put 更新而非新增', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't6', limit: 10 });
  cache.put(rec('a', 1, 1, { title: 'old' }));
  cache.put(rec('a', 2, 2, { title: 'new' }));
  assert.equal(cache.list().length, 1);
  assert.equal(cache.get('a').title, 'new');
});

test('cache：stats 计数与 clear 清空', () => {
  const cache = createCache({ storage: makeMemStorage(), namespace: 't7', limit: 10 });
  cache.put(rec('a', 1, 500));
  const s = cache.stats();
  assert.equal(s.count, 1);
  assert.equal(s.lastAt, 500);
  cache.clear();
  assert.equal(cache.list().length, 0);
});