#!/usr/bin/env node
'use strict';
// demo.js —— 完全离线的一键演示（npm run demo）
// 真实 require 业务代码：内存 storage 驱动 createCache；createMockAIAdapter（脚本为合法 JSON）
// 驱动 createAgent 的成功流式路径；同步抛错适配器驱动 agent 内部降级到 local-engine。
// 无 wx、无网络。退出码非 0 表示演示失败。
const path = require('path');
const SRC = path.join(__dirname, '..', 'src');

// ---------- 内置演示数据 ----------
const DOC = [
  'XX科技（股票代码 007001）2025 年年度报告显示，公司全年实现营业收入 128.6 亿元，同比增长 23.4%，',
  '归属于上市公司股东的净利润为 18.9 亿元，同比增长 31.2%，净利润率由上年的 12.1% 提升至 14.7%。',
  '分业务看，智能硬件板块收入 76.3 亿元，占比 59.3%；云服务板块收入 38.1 亿元，同比增长 45.8%，',
  '成为增长最快的业务线；其余收入 14.2 亿元，同比微降 2.1%。',
  '分季度看，第四季度单季营收 41.2 亿元，同比增长 26.5%，环比增长 9.3%；智能硬件出货量 1250 万台，同比增长 18.6%。',
  '报告期内，公司研发投入 15.7 亿元，占营业收入比重 12.2%，较上年提高 1.8 个百分点，累计获得授权专利 2143 项。',
  '毛利率为 34.6%，同比下降 1.4 个百分点，主要因上游原材料价格上涨约 8% 所致。',
  '经营性现金流净额 22.3 亿元，同比增长 18.9%；资产负债率 41.2%，较上年末下降 3.5 个百分点，财务结构保持稳健。',
  '截至报告期末，公司员工总数 8600 人，研发人员占比 27.4%，累计付费企业客户 3.2 万家，净收入留存率 118%。',
  '风险方面，前五大客户贡献收入 55.6%，客户集中度偏高；海外收入占比 19.3%，受汇率波动影响，',
  '汇兑损失约 0.7 亿元。管理层在展望中提出 2026 年收入目标增速不低于 20%，并计划将分红比例提升至 35%。'
].join('');

const SCHEDULE = [
  '今天下班前提交报销单',
  '明天上午 9:00 参加 Q4 战略复盘会，需准备增长数据',
  '下午 3:00 与设计师评审秒开骨架屏',
  '周五前完成一页纸快读的功能自测',
  '报名 10 月 17 日小程序大赛截止前提交材料',
  '回复张总邮件',
  '回复张总邮件',
  '晚上 8:00 健身房锻炼',
  '准备明天晨会 5 分钟讲稿',
  '顺便清理手机相册',
  '有空了解一下 uni-app 和原生小程序的差异',
  '不急，改天研究竞品新发布的版本',
  '给妈妈打电话（每周重复）'
].join('\n');

// ---------- mock 流式脚本：agent 会把分片拼成合法 JSON 并解析为结构化 ----------
const QUICK_JSON = JSON.stringify({
  conclusion: 'XX科技2025年营收 128.6 亿元（+23.4%）、净利 18.9 亿元（+31.2%），云服务与研发双轮驱动，现金流与财务结构稳健。',
  keyData: [
    { value: '128.6亿元', label: '营业收入 同比+23.4%' },
    { value: '18.9亿元', label: '归母净利润 同比+31.2%' },
    { value: '22.3亿元', label: '经营性现金流净额 同比+18.9%' },
    { value: '38.1亿元', label: '云服务收入 同比+45.8%' },
    { value: '15.7亿元', label: '研发投入 占比12.2%' }
  ],
  risks: [
    { text: '前五大客户贡献收入 55.6%，客户集中度偏高', terms: ['集中度高'] },
    { text: '海外收入占比 19.3%，汇率波动致汇兑损失约 0.7 亿元', terms: ['汇率', '波动'] },
    { text: '毛利率 34.6% 同比下降 1.4 个百分点，原材料涨价约 8%', terms: ['下降', '涨价'] }
  ],
  evidence: [
    { text: '全年实现营业收入 128.6 亿元，同比增长 23.4%' },
    { text: '归属于上市公司股东的净利润为 18.9 亿元，同比增长 31.2%' },
    { text: '经营性现金流净额 22.3 亿元，同比增长 18.9%' }
  ]
});

const TRIAGE_JSON = JSON.stringify({
  today: [
    { text: '报名 10 月 17 日小程序大赛截止前提交材料' },
    { text: '明天上午 9:00 参加 Q4 战略复盘会' },
    { text: '下午 3:00 与设计师评审秒开骨架屏' }
  ],
  defer: ['回复张总邮件', '晚上 8:00 健身房锻炼', '给妈妈打电话（每周重复）'],
  deletions: [
    { item: '顺便清理手机相册', reason: '低价值：无截止时间且非紧急，仅挤占注意力' },
    { item: '有空了解一下 uni-app 和原生小程序的差异', reason: '含犹豫词（有空/了解一下），合并进竞品对比一次性处理' },
    { item: '不急，改天研究竞品新发布的版本', reason: '重复：与上一条竞品事项同源，删除后无连带损失' }
  ],
  timeBlocks: [
    { start: '09:00', end: '10:30', label: 'Q4 战略复盘会', type: 'must' },
    { start: '10:30', end: '12:00', label: '大赛截止材料', type: 'must' },
    { start: '14:00', end: '15:00', label: '秒开骨架屏评审', type: 'must' },
    { start: '15:00', end: '15:45', label: '缓冲/休息', type: 'break' }
  ]
});

function splitFixed(str, size) {
  const out = [];
  for (let i = 0; i < str.length; i += size) out.push(str.slice(i, i + size));
  return out;
}

// ---------- 内存 storage（cache/telemetry 的注入点） ----------
function createMemoryStorage() {
  const map = new Map();
  return {
    getSync(k) { return map.has(k) ? map.get(k) : null; },
    setSync(k, v) { map.set(k, v); },
    removeSync(k) { map.delete(k); },
  };
}

// ---------- 任意调用即同步抛错的适配器：验证 agent 内部 catch → 降级 local-engine ----------
function makeThrowingAI(msg) {
  return {
    isAvailable() { return true; },
    streamText() { throw new Error(msg); },
    agentChat() { throw new Error(msg); },
    cancel() {},
  };
}

function renderStructured(obj, depth) {
  depth = depth || 0;
  const pad = '    '.repeat(depth);
  const lines = [];
  if (obj === null || obj === undefined) return [pad + '(空)'];
  if (Array.isArray(obj)) {
    if (obj.length === 0) return [pad + '[]'];
    obj.slice(0, 8).forEach(v => {
      if (v && typeof v === 'object') lines.push(...renderStructured(v, depth + 1));
      else lines.push(pad + ' - ' + String(v));
    });
    if (obj.length > 8) lines.push(pad + ' … 共 ' + obj.length + ' 项');
    return lines;
  }
  if (typeof obj === 'object') {
    for (const [k, v] of Object.entries(obj)) {
      if (v && typeof v === 'object') { lines.push(pad + k + ':'); lines.push(...renderStructured(v, depth + 1)); }
      else lines.push(pad + k + ': ' + String(v));
    }
    return lines;
  }
  return [pad + String(obj)];
}

function extractNumbers(text) {
  const re = /(\d+(?:\.\d+)?)\s*(%|亿元|亿|万元|万|个百分点|项|台|家|人)/g;
  const out = [];
  let m;
  while ((m = re.exec(text))) if (m[2]) out.push(m[1] + m[2]);
  return [...new Set(out)];
}

function hr(title) {
  console.log('\n' + '='.repeat(56));
  console.log('  ' + title);
  console.log('='.repeat(56));
}

async function main() {
  let decode, cacheMod, le, agentMod, adapterMod, busMod;
  try {
    decode = require(path.join(SRC, 'utils', 'decode.js'));
    cacheMod = require(path.join(SRC, 'utils', 'cache.js'));
    le = require(path.join(SRC, 'core', 'local-engine.js'));
    agentMod = require(path.join(SRC, 'core', 'agent.js'));
    adapterMod = require(path.join(SRC, 'core', 'ai-adapter.js'));
    busMod = require(path.join(SRC, 'core', 'stream-bus.js'));
  } catch (e) {
    console.error('[致命] 无法 require 业务代码，src/ 尚未就绪：' + e.message);
    process.exitCode = 1;
    return;
  }

  const storage = createMemoryStorage();
  const clock = { now: () => Date.now() };
  let allPass = true;
  const pass = (label, ok) => {
    console.log(`[自检] ${label}：${ok ? 'PASS ✅' : 'FAIL ❌'}`);
    if (!ok) allPass = false;
  };

  // ============================ 链路一：一页纸快读 ============================
  hr('链路一 · AI 一页纸快读（财报长文 ' + DOC.length + ' 字）');

  const cache1 = cacheMod.createCache({ storage, namespace: 'quickread', limit: 50 });
  const keyId = decode.hashString(DOC);
  cache1.put({
    id: keyId, scene: 'quickread',
    title: 'XX科技 2025 年报 · 一页纸',
    summary: '营收 128.6 亿(+23.4%)，净利 18.9 亿(+31.2%)，经营现金流 22.3 亿(+18.9%)',
    raw: DOC.slice(0, 80), ts: Date.now() - 3600000, hit: 2, score: 0.91,
    tags: ['财报', '年报', '增长'], meta: { model: 'mock-cached' },
  });

  const t0 = process.hrtime.bigint();
  const cached1 = cache1.get(keyId);
  console.log(`[秒开] t0 同步读缓存 ${(Number(process.hrtime.bigint() - t0) / 1e6).toFixed(3)} ms，首帧渲染标题「${cached1.title}」`);

  // —— 成功路径：mock 适配器流式返回合法 JSON ——
  const bus1 = busMod.createStreamBus();
  const ag1 = agentMod.createAgent({ scene: 'quickread', ai: adapterMod.createMockAIAdapter({ latency: 5, script: splitFixed(QUICK_JSON, 72) }), clock, bus: bus1 });
  const frames = [];
  const runStart = Date.now();
  const quickRes = await ag1.run(DOC, { onStep: (s) => { if (s && s.kind === 'skeleton' && frames.skel === undefined) frames.skel = s.text; if (s && s.kind === 'text' && s.text) frames.push(s.text); } });
  const textFrames = frames.filter(f => typeof f === 'string');
  console.log(`[骨架] 首帧步骤「${frames.skel || (quickRes.steps[0] && quickRes.steps[0].text)}」`);
  console.log(`[流式] 合并后 ${textFrames.length} 个增量片段，总长 ${textFrames.join('').length} 字，mode=${quickRes.usage.mode} fallbackUsed=${quickRes.fallbackUsed}`);
  console.log(`[耗时] 端到端 ${quickRes.usage.ms} ms（model=${quickRes.usage.model}）`);
  console.log('[结构化] 关键字段表：');
  console.log(renderStructured(quickRes.structured).map(l => '    ' + l).join('\n'));
  pass('云端成功路径 mode=stream 且 fallbackUsed=false', quickRes.usage.mode === 'stream' && quickRes.fallbackUsed === false && !!quickRes.structured && !!quickRes.structured.conclusion);

  // —— 降级路径：streamText 同步抛错 → agent 内部 catch → local-engine ——
  const bus1b = busMod.createStreamBus();
  const ag1b = agentMod.createAgent({ scene: 'quickread', ai: makeThrowingAI('模拟云端故障：streamText 同步抛错'), clock, bus: bus1b });
  const degrade1 = await ag1b.run(DOC, { onStep() {} });
  console.log(`[降级] 原因=streamText 同步抛错；agent 已兜底 fallbackUsed=${degrade1.fallbackUsed} mode=${degrade1.usage.mode}，结构化结果仍非空=${!!(degrade1.structured && degrade1.structured.conclusion)}`);
  console.log(`[降级] local-engine 输出 keyData：${(degrade1.structured.keyData || []).map(d => d.value).slice(0, 6).join('、')}`);
  pass('抛错降级 mode=local 且 structured 非空', degrade1.usage.mode === 'local' && degrade1.fallbackUsed === true && !!degrade1.structured && (degrade1.structured.keyData || []).length > 0);

  console.log('    提取关键数字: ' + extractNumbers(DOC).join('、'));

  const qa = JSON.stringify(le.analyzeDocument(DOC, { maxSentences: 5 }));
  const qb = JSON.stringify(le.analyzeDocument(DOC, { maxSentences: 5 }));
  pass('同输入两次 analyzeDocument 全等', qa === qb);

  // ============================ 链路二：日程断舍离 ============================
  hr('链路二 · 个人日程断舍离（' + SCHEDULE.split('\n').length + ' 条待办）');

  const cache2 = cacheMod.createCache({ storage, namespace: 'triage', limit: 50 });
  const skey = decode.hashString(SCHEDULE);
  cache2.put({
    id: skey, scene: 'triage', title: '今日待办 · 断舍离',
    summary: '建议删除 3 条低价值事项', raw: SCHEDULE.slice(0, 60),
    ts: Date.now() - 60000, hit: 1, score: 0.88, tags: ['日程', '待办'], meta: {},
  });
  const t1 = process.hrtime.bigint();
  const cached2 = cache2.get(skey);
  console.log(`[秒开] t0 同步读缓存 ${(Number(process.hrtime.bigint() - t1) / 1e6).toFixed(3)} ms，首屏显示「${cached2.title}」`);

  const bus2 = busMod.createStreamBus();
  const ag2 = agentMod.createAgent({ scene: 'triage', ai: adapterMod.createMockAIAdapter({ latency: 3, script: splitFixed(TRIAGE_JSON, 64) }), clock, bus: bus2 });
  const sFrames = [];
  let skelShown = false;
  const triRes = await ag2.run(SCHEDULE, { onStep: (s) => { if (s && s.kind === 'skeleton' && !skelShown) { sFrames.skel = s.text; skelShown = true; } if (s && s.kind === 'text' && s.text) sFrames.push(s.text); } });
  console.log(`[骨架] 首帧步骤「${sFrames.skel || (triRes.steps[0] && triRes.steps[0].text)}」`);
  console.log(`[流式] 合并后 ${sFrames.filter(f => typeof f === 'string').length} 个增量片段，mode=${triRes.usage.mode}`);
  console.log(`[耗时] 端到端 ${triRes.usage.ms} ms（model=${triRes.usage.model}）`);
  console.log('[结构化] 断舍离建议表：');
  console.log(renderStructured(triRes.structured).map(l => '    ' + l).join('\n'));

  const bus2b = busMod.createStreamBus();
  const ag2b = agentMod.createAgent({ scene: 'triage', ai: makeThrowingAI('模拟云端故障'), clock, bus: bus2b });
  const degrade2 = await ag2b.run(SCHEDULE, { onStep() {} });
  console.log(`[降级] 原因=云端不可用；fallbackUsed=${degrade2.fallbackUsed} mode=${degrade2.usage.mode}，删除建议 ${(degrade2.structured.deletions || []).length} 条`);
  (degrade2.structured.deletions || []).forEach(d => console.log(`    - 建议删除：${d.item}（${d.reason}）`));
  pass('triage 成功路径 mode=stream', triRes.usage.mode === 'stream' && !!triRes.structured && (triRes.structured.today || []).length > 0);
  pass('triage 抛错降级 mode=local 且 today 非空', degrade2.usage.mode === 'local' && (degrade2.structured.today || []).length > 0);

  const sa = JSON.stringify(le.analyzeSchedule(SCHEDULE, { now: 1700000000000 }));
  const sb = JSON.stringify(le.analyzeSchedule(SCHEDULE, { now: 1700000000000 }));
  pass('同输入固定 now 两次 analyzeSchedule 全等', sa === sb);

  hr('演示完成');
  console.log('两条链路均离线跑通：秒开(t0 同步缓存) → 骨架首帧 → 流式增量 → 结构化卡片 → 抛错降级兜底。');
  if (!allPass) {
    console.error('❌ 存在自检失败项，退出码 1');
    process.exitCode = 1;
  } else {
    console.log('✅ 全部自检通过，退出码 0');
  }
}

main().catch(e => {
  console.error('[致命] 演示异常终止：', e && e.stack ? e.stack : e);
  process.exitCode = 1;
});