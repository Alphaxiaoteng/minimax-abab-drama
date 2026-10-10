'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createSSEParser, parseAGUIEvent, mapAGUIEventToStep } = require('../src/utils/sse.js');

test('SSE 解析：一条事件被切成 3 段仍能凑成完整帧', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (raw) => got.push(raw) });
  p.feed('data: hel');
  p.feed('lo\n');
  p.feed('\n');
  assert.deepEqual(got, ['hello']);
});

test('SSE 解析：同帧多行 data 以换行拼接', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (r) => got.push(r) });
  p.feed('data: a\ndata: b\n\n');
  assert.deepEqual(got, ['a\nb']);
});

test('SSE 解析：心跳注释行不派发', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (r) => got.push(r) });
  p.feed(': heartbeat\n\n');
  assert.deepEqual(got, []);
});

test('SSE 解析：兼容 CRLF 帧分隔符', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (r) => got.push(r) });
  p.feed('data: x\r\n\r\n');
  assert.deepEqual(got, ['x']);
});

test('SSE 解析：flush 收尾无终止空行的尾帧', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (r) => got.push(r) });
  p.feed('data: tail');
  p.flush();
  assert.deepEqual(got, ['tail']);
});

test('SSE 解析：[DONE] 原样透传', () => {
  const got = [];
  const p = createSSEParser({ onEvent: (r) => got.push(r) });
  p.feed('data: [DONE]\n\n');
  assert.deepEqual(got, ['[DONE]']);
});

test('parseAGUIEvent：文本增量', () => {
  const e = parseAGUIEvent(JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', delta: '你好' }));
  assert.equal(e.type, 'TEXT_MESSAGE_CONTENT');
  assert.equal(e.delta, '你好');
});

test('parseAGUIEvent：非法 JSON 归为 UNKNOWN 且不抛', () => {
  const e = parseAGUIEvent('not-json');
  assert.equal(e.type, 'UNKNOWN');
  assert.equal(e.data, 'not-json');
  assert.equal(e.delta, '');
});

test('mapAGUIEventToStep：事件到 UI kind 映射', () => {
  assert.deepEqual(mapAGUIEventToStep({ type: 'TEXT_MESSAGE_CONTENT', delta: 'a' }), { kind: 'text', text: 'a' });
  assert.deepEqual(mapAGUIEventToStep({ type: 'TOOL_CALL_START', toolCallName: 'get_weather' }), { kind: 'tool', text: 'get_weather' });
  assert.deepEqual(mapAGUIEventToStep({ type: 'TOOL_CALL_ARGS', delta: '{' }), { kind: 'think', text: '{' });
  assert.deepEqual(mapAGUIEventToStep({ type: 'RUN_FINISHED' }), { kind: 'done', text: '' });
  assert.deepEqual(mapAGUIEventToStep({ type: 'RUN_ERROR', message: '崩了' }), { kind: 'error', text: '崩了' });
  assert.deepEqual(mapAGUIEventToStep({ type: 'STATE_SNAPSHOT' }), { kind: 'artifact', text: '' });
  assert.deepEqual(mapAGUIEventToStep({}), { kind: 'text', text: '' });
});