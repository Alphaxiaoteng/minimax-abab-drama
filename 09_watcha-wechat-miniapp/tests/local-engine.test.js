'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  analyzeDocument,
  analyzeSchedule,
  localAnswer,
  localChat
} = require('../src/core/local-engine.js');

// 含明确数字与风险信号的财报样本，用于验证「真实计算」而非硬编码。
const DOC_SAMPLE = [
  '公司本季度实现营业收入 128.6 亿元，同比增长 23.4%。',
  '归母净利润 15.7 亿元，净利率提升至 12.2%。',
  '研发投入 14.2 亿元，占营业收入 11.0%。',
  '因产品质量问题被监管部门责令召回部分批次，涉及金额 1250 万元。',
  '公司面临行业竞争加剧压力，预计增速将放缓至 15%。'
].join('\n');

test('analyzeDocument：同输入两次结果全等（确定性）', () => {
  const a = analyzeDocument(DOC_SAMPLE, { maxSentences: 3 });
  const b = analyzeDocument(DOC_SAMPLE, { maxSentences: 3 });
  assert.deepEqual(a, b);
});

test('analyzeDocument：真实提取出样本中的具体数字', () => {
  const { structured } = analyzeDocument(DOC_SAMPLE, { maxSentences: 3 });
  const values = structured.keyData.map((d) => d.value);
  assert.ok(values.some((v) => v.includes('128.6')), '应提取 128.6 亿元');
  assert.ok(values.some((v) => v.includes('23.4')), '应提取 23.4%');
});

test('analyzeDocument：命中风险词表时产出风险点并附原文引用', () => {
  const { structured } = analyzeDocument(DOC_SAMPLE, { maxSentences: 3 });
  assert.ok(structured.risks.length > 0, '监管/召回/竞争加剧应被识别为风险');
  for (const r of structured.risks) {
    assert.ok(typeof r.text === 'string' && r.text.length > 0);
    assert.ok(typeof r.evidence === 'string' && r.evidence.length > 0);
  }
});

test('analyzeDocument：无数字样本时 keyData 如实为空，绝不编造', () => {
  const { structured } = analyzeDocument('这是一段完全没有任何数字的纯文字叙述内容。', { maxSentences: 3 });
  assert.equal(structured.keyData.length, 0);
  assert.ok(typeof structured.conclusion === 'string');
});

test('analyzeDocument：空输入返回可渲染结构而非抛异常', () => {
  const { structured } = analyzeDocument('');
  assert.equal(structured.keyData.length, 0);
  assert.equal(structured.risks.length, 0);
  assert.ok(typeof structured.conclusion === 'string');
});

const SCHED_SAMPLE = [
  '紧急：明天 9:00 提交大赛材料',
  '下午 3:00 与设计师评审秒开骨架屏',
  '准备下周三客户签约提案',
  '顺便清理手机相册',
  '有空了解一下框架的差异'
].join('\n');

test('analyzeSchedule：固定 now 同输入两次全等（确定性）', () => {
  const a = analyzeSchedule(SCHED_SAMPLE, { now: 1730000000000 });
  const b = analyzeSchedule(SCHED_SAMPLE, { now: 1730000000000 });
  assert.deepEqual(a, b);
});

test('analyzeSchedule：高优先级进入 today，噪声项给出删除理由', () => {
  const { structured } = analyzeSchedule(SCHED_SAMPLE, { now: 1730000000000 });
  assert.ok(structured.today.length > 0);
  assert.ok(structured.today[0].text.includes('紧急'));
  assert.ok(structured.deletions.some((d) => d.item.includes('顺便') && d.reason.length > 0));
  assert.ok(Array.isArray(structured.timeBlocks) && structured.timeBlocks.length > 0);
});

test('analyzeSchedule：空输入不抛异常', () => {
  const { structured } = analyzeSchedule('', { now: 0 });
  assert.deepEqual(structured.today, []);
});

test('localAnswer：基于已有 structured 做确定性追问回答', () => {
  const ctx = analyzeDocument(DOC_SAMPLE, { maxSentences: 3 });
  const ans = localAnswer('有哪些风险？', ctx);
  assert.ok(ans.includes('风险'));
});

test('localChat：按场景返回引导文本', () => {
  assert.ok(localChat('随便', 'triage').includes('待办'));
  assert.ok(localChat('随便', 'quickread').includes('一页纸'));
});