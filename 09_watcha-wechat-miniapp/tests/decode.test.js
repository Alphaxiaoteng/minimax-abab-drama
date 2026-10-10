'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  normalizeInput,
  splitSentences,
  tokenize,
  estimateTokens,
  chunkText,
  hashString,
  formatClock
} = require('../src/utils/decode.js');

test('normalizeInput：空值/换行/零宽/连续空行', () => {
  assert.equal(normalizeInput(null), '');
  assert.equal(normalizeInput(undefined), '');
  assert.equal(normalizeInput('a\r\nb\rc'), 'a\nb\nc');
  assert.equal(normalizeInput('​你好​'), '你好');
  assert.equal(normalizeInput('x\n\n\n\ny'), 'x\n\ny');
});

test('splitSentences：中文句末标点切分、小数点不误切', () => {
  assert.deepEqual(splitSentences('你好。世界！'), ['你好。', '世界！']);
  assert.deepEqual(splitSentences('价 3.14 元'), ['价 3.14 元']);
  assert.deepEqual(splitSentences(''), []);
});

test('tokenize：英文按词、中文 2-gram+单字', () => {
  assert.deepEqual(tokenize('AI'), ['ai']);
  assert.deepEqual(tokenize('你好'), ['你', '你好', '好']);
  assert.deepEqual(tokenize(''), []);
});

test('estimateTokens：中文≈1字、英文4字符≈1', () => {
  assert.equal(estimateTokens('你好'), 2);
  assert.equal(estimateTokens('abcd'), 1);
  assert.equal(estimateTokens(''), 0);
});

test('chunkText：按句切块不截断句子', () => {
  const chunks = chunkText('一二三。四五六。', 4);
  assert.deepEqual(chunks, ['一二三。', '四五六。']);
  for (const c of chunks) assert.ok(!c.includes('…'));
});

test('hashString：稳定、可复现、8 位十六进制', () => {
  assert.equal(hashString('abc'), hashString('abc'));
  assert.notEqual(hashString('abc'), hashString('abd'));
  assert.match(hashString('x'), /^[0-9a-f]{8}$/);
});

test('formatClock：输出 MM-DD HH:mm', () => {
  const s = formatClock(1730000000000);
  assert.match(s, /^\d{2}-\d{2} \d{2}:\d{2}$/);
  assert.equal(formatClock(new Date(1730000000000)), s);
});