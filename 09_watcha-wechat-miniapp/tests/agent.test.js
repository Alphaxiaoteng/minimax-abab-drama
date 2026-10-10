'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createAgent, parseStructured } = require('../src/core/agent.js');
const { createMockAIAdapter } = require('../src/core/ai-adapter.js');
const { createStreamBus } = require('../src/core/stream-bus.js');

const DOC = '公司实现营业收入 128.6 亿元，同比增长 23.4%。因召回被监管责令整改。';

// 成功流：分片拼成合法 JSON，验证真走云端解析路径。
function successAi() {
  return createMockAIAdapter({
    latency: 0,
    script: [
      '{"conclusion":"结论A"',
      ',"keyData":[{"value":"23.4%","label":"增速"}]',
      ',"risks":[{"text":"召回"}],"evidence":[]}'
    ]
  });
}

test('agent.run：成功路径首帧是 skeleton，随后 stream 且未降级', async () => {
  const bus = createStreamBus();
  const agent = createAgent({ scene: 'quickread', ai: successAi(), bus });
  const res = await agent.run(DOC);

  assert.equal(res.fallbackUsed, false);
  assert.equal(res.usage.mode, 'stream');
  assert.equal(res.structured.conclusion, '结论A');
  assert.equal(res.steps[0].kind, 'skeleton', '骨架必须先行');
});

test('agent.run：ai 不可用时静默降级 local-engine 且 structured 非空', async () => {
  const failAi = createMockAIAdapter({ fail: true, latency: 0 });
  const agent = createAgent({ scene: 'quickread', ai: failAi });
  const res = await agent.run(DOC);

  assert.equal(res.fallbackUsed, true);
  assert.equal(res.usage.mode, 'local');
  assert.ok(res.structured.keyData.length > 0, 'local 仍应真实提取 128.6/23.4');
});

test('agent.run：streamText 同步抛错被捕获并降级', async () => {
  const throwAi = {
    isAvailable: () => true,
    streamText: () => { throw new Error('boom'); },
    agentChat: async () => ({ ok: false }),
    cancel: () => {}
  };
  const agent = createAgent({ scene: 'quickread', ai: throwAi });
  const res = await agent.run(DOC);

  assert.equal(res.fallbackUsed, true);
  assert.equal(res.usage.mode, 'local');
});

test('agent.run：超时触发降级', async () => {
  const neverAi = {
    isAvailable: () => true,
    streamText: () => new Promise(() => {}), // 永不 resolve
    agentChat: async () => ({ ok: false }),
    cancel: () => {}
  };
  const agent = createAgent({ scene: 'quickread', ai: neverAi, timeoutMs: 20 });
  const res = await agent.run(DOC);

  assert.equal(res.fallbackUsed, true);
  assert.equal(res.usage.mode, 'local');
});

test('agent.ask：未运行前返回场景引导，运行后返回结构化追问', async () => {
  const agent = createAgent({ scene: 'quickread', ai: createMockAIAdapter({ fail: true }) });
  const before = await agent.ask('有什么风险');
  assert.ok(before.text.length > 0);
  assert.equal(before.fallbackUsed, true); // AGENT_BOT_ID 为空 → 本地

  await agent.run(DOC);
  const after = await agent.ask('有哪些风险点？');
  assert.ok(after.text.includes('风险'));
});

test('agent.abort：中断不抛异常', async () => {
  const agent = createAgent({ scene: 'quickread', ai: createMockAIAdapter({ fail: true }) });
  assert.doesNotThrow(() => agent.abort());
});

test('parseStructured：解析围栏包裹与非法 JSON', () => {
  const ok = parseStructured('```json\n{"conclusion":"x"}\n```', 'quickread');
  assert.equal(ok.conclusion, 'x');
  assert.equal(parseStructured('不是 JSON', 'quickread'), null);
  assert.equal(parseStructured('{"foo":1}', 'quickread'), null, '空壳视为失败');
});