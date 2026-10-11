// 自动生成，勿手改：node tools/build-h5-sim.js
// 源模块与小程序运行时共用同一份代码，保证同输入同输出的确定性行为一致。
(function (global) {
  var __registry = {};
  var __cache = {};
  function __def(id, fn) { __registry[id] = fn; }
  function __require(id) {
    if (__cache[id]) return __cache[id].exports;
    var mod = { exports: {} };
    __cache[id] = mod;
    __registry[id](mod, mod.exports, __require);
    return mod.exports;
  }
  __def('utils/decode.js', function (module, exports, __require) {
// 文本预处理与轻量分词，供 local-engine 的摘要打分 / 关键数据提取复用。
// 全部函数必须是纯函数、确定性（同输入同输出），不读系统时间、不依赖外部状态。

// 零宽字符与软连字符：肉眼不可见但会干扰正则与分词，归一时统一清掉。
const ZERO_WIDTH = /[​-‍﻿­]/g;
// 全角连字符归一为半角，避免同义符号割裂词形。
const HYPHEN_UNIFY = /[－﹣‐‑‒]/g;

function normalizeInput(text) {
  if (text === null || text === undefined) return '';
  let s = String(text);
  // 统一换行
  s = s.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  // 清零宽 / 软连字符
  s = s.replace(ZERO_WIDTH, '');
  // 连字符归一
  s = s.replace(HYPHEN_UNIFY, '-');
  // 英文换行连字符断词：word-\nword -> wordword
  s = s.replace(/-\n(?=[A-Za-z])/g, '');
  // 压缩连续空行至最多一个
  s = s.replace(/\n{3,}/g, '\n\n');
  // 行尾多余空格
  s = s.replace(/[ \t]+\n/g, '\n');
  return s.trim();
}

// 按中英文句末标点与换行切句，不做句子内部截断。
// 小数点（3.14）与年份不切：'.' 仅在其后为空白或行尾、且前一个非数字时才断句。
function splitSentences(text) {
  const s = String(text === null || text === undefined ? '' : text);
  const out = [];
  let buf = '';
  const BREAK = '。！？；!?;\n';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    buf += ch;
    if (BREAK.indexOf(ch) !== -1) {
      pushTrimmed(out, buf);
      buf = '';
      continue;
    }
    if (ch === '.' || ch === '…') {
      const prev = s[i - 1] || '';
      const next = s[i + 1] || '';
      const prevIsDigit = prev >= '0' && prev <= '9';
      if (ch === '…' || (!prevIsDigit && (next === '' || next === ' ' || next === '\n'))) {
        pushTrimmed(out, buf);
        buf = '';
      }
    }
  }
  pushTrimmed(out, buf);
  return out;
}

function pushTrimmed(arr, chunk) {
  const t = chunk.trim();
  if (t) arr.push(t);
}

// 中英混合分词：英文按词，中文按 2-gram + 单字，保证 TF 统计可区分词形。
function tokenize(text) {
  const s = String(text === null || text === undefined ? '' : text).toLowerCase();
  const runs = s.match(/[一-龥]+|[a-z0-9]+/g) || [];
  const tokens = [];
  for (const run of runs) {
    if (/^[a-z0-9]+$/.test(run)) {
      tokens.push(run);
    } else {
      for (let i = 0; i < run.length; i++) {
        tokens.push(run[i]);
        if (i < run.length - 1) tokens.push(run[i] + run[i + 1]);
      }
    }
  }
  return tokens;
}

function countCjk(s) {
  const m = s.match(/[一-龥]/g);
  return m ? m.length : 0;
}

// 粗估 token：中文字符≈1，英文/数字 4 字符≈1。
function estimateTokens(text) {
  const s = String(text === null || text === undefined ? '' : text);
  const cjk = countCjk(s);
  const other = s.length - cjk;
  return cjk + Math.ceil(other / 4);
}

// 按句边界切块，单句超过 maxChars 时单独成块（不截断句子）。
function chunkText(text, maxChars) {
  const limit = maxChars && maxChars > 0 ? maxChars : 1200;
  const sentences = splitSentences(normalizeInput(text));
  const chunks = [];
  let cur = '';
  for (const sent of sentences) {
    if (sent.length > limit) {
      if (cur) { chunks.push(cur); cur = ''; }
      chunks.push(sent);
      continue;
    }
    if ((cur + sent).length > limit) {
      if (cur) chunks.push(cur);
      cur = sent;
    } else {
      cur = cur ? cur + sent : sent;
    }
  }
  if (cur) chunks.push(cur);
  return chunks;
}

// 32 位 FNV-1a 哈希，稳定可复现，用于离线去重 / cache id 派生。
function hashString(str) {
  const s = String(str === null || str === undefined ? '' : str);
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return ('00000000' + h.toString(16)).slice(-8);
}

function pad2(n) {
  return (n < 10 ? '0' : '') + n;
}

// ts 为毫秒数或 Date，输出本地时区 'MM-DD HH:mm'。
function formatClock(ts) {
  const d = ts instanceof Date ? ts : new Date(typeof ts === 'number' ? ts : Number(ts) || 0);
  return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

module.exports = {
  normalizeInput,
  splitSentences,
  tokenize,
  estimateTokens,
  chunkText,
  hashString,
  formatClock
};
  });
  __def('utils/cache.js', function (module, exports, __require) {
// 最近记录缓存。核心卖点「秒开」依赖它：app 启动同步 load + rank，直接 setData，零网络阻塞。
// storage 抽象出 getSync/setSync/removeSync，方便 wx 实现与 Node 测试的内存实现共用同一套逻辑。

function createCache({ storage, namespace, limit } = {}) {
  if (!storage || typeof storage.getSync !== 'function' || typeof storage.setSync !== 'function') {
    throw new Error('cache: storage 必须实现 getSync/setSync');
  }
  const ns = namespace || 'wa_cache';
  const cap = limit && limit > 0 ? limit : 30;
  const key = ns + '__items';

  function persist(items) {
    storage.setSync(key, { items, updatedAt: Date.now() });
  }

  function load() {
    const raw = storage.getSync(key);
    if (raw && Array.isArray(raw.items)) return { items: raw.items.slice(0, cap) };
    return { items: [] };
  }

  function normalizeRecord(record) {
    const r = record || {};
    return {
      id: r.id || ('rec_' + Date.now() + '_' + hash(r)),
      scene: r.scene || 'quickread',
      title: r.title || '未命名',
      summary: r.summary || '',
      raw: r.raw || '',
      ts: typeof r.ts === 'number' ? r.ts : Date.now(),
      hit: typeof r.hit === 'number' ? r.hit : 0,
      score: typeof r.score === 'number' ? r.score : 0,
      tags: Array.isArray(r.tags) ? r.tags : [],
      meta: r.meta || {}
    };
  }

  function hash(r) {
    let h = 0;
    const s = String(r.raw || r.title || '');
    for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
    return h.toString(16);
  }

  function put(record) {
    const norm = normalizeRecord(record);
    const current = load().items;
    const idx = current.findIndex(function (it) { return it.id === norm.id; });
    if (idx !== -1) { current[idx] = norm; } else { current.unshift(norm); }
    if (current.length > cap) current.length = cap;
    persist(current);
    return norm;
  }

  function list() { return load().items; }

  function get(id) {
    const found = load().items.find(function (it) { return it.id === id; });
    return found || null;
  }

  // 按 score 降序、ts 降序排列，用于首页 Top N 秒开。
  function rank() {
    return load().items.slice().sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return b.ts - a.ts;
    });
  }

  function search(keyword) {
    if (!keyword) return load().items;
    const kw = String(keyword).toLowerCase();
    return load().items.filter(function (it) {
      return (it.title + it.summary + it.raw).toLowerCase().indexOf(kw) !== -1;
    });
  }

  function remove(id) {
    const current = load().items;
    const next = current.filter(function (it) { return it.id !== id; });
    if (next.length !== current.length) { persist(next); return true; }
    return false;
  }

  function stats() {
    const items = load().items;
    let bytes = 0;
    let lastAt = 0;
    for (const it of items) {
      bytes += JSON.stringify(it).length;
      if (it.ts > lastAt) lastAt = it.ts;
    }
    return { count: items.length, hitEstimate: items.length, bytes: bytes, lastAt: lastAt };
  }

  function clear() {
    storage.removeSync(key);
  }

  return { load, put, list, get, rank, search, remove, stats, clear };
}

function createWxStorage() {
  return {
    getSync: function (k) { try { return wx.getStorageSync(k) || null; } catch (e) { return null; } },
    setSync: function (k, v) { try { wx.setStorageSync(k, v); } catch (e) {} },
    removeSync: function (k) { try { wx.removeStorageSync(k); } catch (e) {} }
  };
}

module.exports = { createCache, createWxStorage };
  });
  __def('core/local-engine.js', function (module, exports, __require) {
// 离线确定性内核：无云环境/基础库过低/调用失败/超时时，agent 降级到这里，保证评委扫码也能完整跑通。
// 铁律：全部函数真实计算（TF-IDF×位置权重摘要、正则提数、词表匹配），禁止硬编码假数据；
// 同输入必须同输出——analyzeDocument 完全不读时间，analyzeSchedule 的时间相关项只由传入的 now 决定。

const { normalizeInput, splitSentences, tokenize, hashString, formatClock } = __require('utils/decode.js');

// 风险词表：命中即把整句列为风险点并附原文引用。词表可按财报/论文场景扩展。
const RISK_TERMS = [
  '下滑', '亏损', '诉讼', '监管', '违约', '召回', '延期', '竞争加剧', '减值', '商誉',
  '处罚', '违规', '退市', '降价', '裁员', '负债', '逾期', '造假', '不确定性',
  '应收账款', '回款', '坏账', '减持', '解禁', '质押', '冻结', '现金流', '价格战', '审计',
  'decline', 'loss', 'lawsuit', 'regulation', 'default', 'recall', 'delay', 'impairment'
];

// 风险穿透 playbook：命中关键词即给风险句贴上「红线类型 + 严重度」，供警示卡渲染。
// 纯词表匹配，同输入同输出；未命中任何类型时归为通用风险信号。
const RISK_PLAYBOOK = [
  { key: 'receivable', label: '应收账款异动', severity: 'high', terms: ['应收账款', '回款', '坏账', '账期'] },
  { key: 'shareholder', label: '大股东减持', severity: 'high', terms: ['减持', '解禁', '清仓', '质押', '冻结', '平仓'] },
  { key: 'goodwill', label: '商誉减值', severity: 'high', terms: ['商誉', '减值'] },
  { key: 'audit', label: '审计非标', severity: 'high', terms: ['审计', '保留意见', '无法表示意见', '造假'] },
  { key: 'regulatory', label: '监管与诉讼', severity: 'high', terms: ['诉讼', '监管', '处罚', '违规', '召回', '责令', '退市'] },
  { key: 'debt', label: '债务逾期', severity: 'high', terms: ['逾期', '违约', '负债', '资金链'] },
  { key: 'cashflow', label: '现金流恶化', severity: 'medium', terms: ['现金流'] },
  { key: 'competition', label: '竞争加剧', severity: 'medium', terms: ['竞争加剧', '价格战', '降价', '份额下滑'] },
  { key: 'growth', label: '业绩下滑', severity: 'medium', terms: ['下滑', '亏损', '延期', '裁员', '不确定性'] }
];

const SEVERITY_RANK = { high: 3, medium: 2, low: 1 };

// 一句可命中多个红线类型；按严重度降序、playbook 顺序升序，保证确定性。
function classifyRiskSentence(sent) {
  const hits = [];
  for (let i = 0; i < RISK_PLAYBOOK.length; i++) {
    const p = RISK_PLAYBOOK[i];
    const matched = [];
    for (const t of p.terms) {
      if (sent.indexOf(t) !== -1) matched.push(t);
    }
    if (matched.length) hits.push({ def: p, order: i, matched: matched });
  }
  hits.sort(function (a, b) {
    const ra = SEVERITY_RANK[a.def.severity] || 0;
    const rb = SEVERITY_RANK[b.def.severity] || 0;
    if (rb !== ra) return rb - ra;
    return a.order - b.order;
  });
  return hits;
}

// 行业竞争格局信号：只抽取含份额/龙头/排名等格局词的原文句，找不到就如实为空。
const LANDSCAPE_TERMS = ['市场份额', '市占率', '市占', '渗透率', '龙头', '排名', '竞争格局', '行业地位', '行业集中度', '装机量', '出货'];

function extractLandscape(sentences) {
  const out = [];
  for (let i = 0; i < sentences.length; i++) {
    const sent = sentences[i];
    const signals = [];
    for (const t of LANDSCAPE_TERMS) {
      if (sent.indexOf(t) !== -1 && signals.indexOf(t) === -1) signals.push(t);
    }
    if (signals.length) out.push({ text: truncate(sent, 100), signals: signals, si: i });
  }
  return out.slice(0, 4);
}

// 命中任一风险词即视为风险句；纯正向词（增长/超预期）不进风险表，避免误判。
function isRiskSentence(sent) {
  for (const t of RISK_TERMS) {
    if (sent.indexOf(t) !== -1) return true;
  }
  return false;
}

// 关键数据提取：数字 + 单位上下文（百分比/金额/年份/倍数），全部来自原文，找不到就返回空数组。
function extractKeyData(sentences) {
  const out = [];
  const seen = new Set();
  const patterns = [
    { re: /(\d[\d,]*(?:\.\d+)?)\s*%/g, kind: 'percent', suffix: '%' },
    { re: /(?:营收|收入|利润|净利|金额|规模|市值|资金|销售额)[^\d]{0,6}([\d,]+(?:\.\d+)?)\s*(亿元|万元|亿|万|元)/g, kind: 'amount', suffix: '' },
    { re: /([\d,]+(?:\.\d+)?)\s*(亿元|万元)/g, kind: 'amount', suffix: '' },
    { re: /(?<!\d)((?:19|20)\d{2})(?:年|年度)/g, kind: 'year', suffix: '年' },
    { re: /(\d[\d,]*(?:\.\d+)?)\s*(倍|个百分点)/g, kind: 'multiple', suffix: '' },
    { re: /(?:同比|环比|增长|下降|提升|减少)\s*(?:约|近|超过|达到)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|个百分点|亿|万)/g, kind: 'delta', suffix: '' }
  ];
  for (let si = 0; si < sentences.length; si++) {
    const sent = sentences[si];
    for (const p of patterns) {
      const re = new RegExp(p.re.source, p.re.flags);
      let m;
      while ((m = re.exec(sent)) !== null) {
        const value = m[1];
        const unit = m[2] || p.suffix || '';
        const label = buildLabel(sent, m.index);
        const id = value + unit + label;
        if (seen.has(id)) continue;
        seen.add(id);
        out.push({
          value: value + (unit ? unit : ''),
          kind: p.kind,
          label: label,
          evidence: truncate(sent, 80),
          si: si
        });
        if (m.index === re.lastIndex) re.lastIndex++;
      }
    }
  }
  return out;
}

// 从数字前后取一小段上下文作为数据标签，便于「关键数据」可读。
function buildLabel(sent, idx) {
  const start = Math.max(0, idx - 12);
  let prefix = sent.slice(start, idx).replace(/[。；;，,\n]/g, ' ').trim();
  const words = prefix.split(/\s+/).filter(Boolean);
  return words.slice(-2).join('') || '关键指标';
}

function truncate(s, n) {
  const clean = s.replace(/\s+/g, ' ').trim();
  return clean.length <= n ? clean : clean.slice(0, n) + '…';
}

// 摘要打分：TF-IDF(句内词频 / 全篇词频) × 位置权重(越靠前越高) × 长度惩罚 × 数字/风险加分。
function summarize(sentences, maxSentences) {
  const limit = maxSentences && maxSentences > 0 ? maxSentences : 3;
  const total = sentences.length;
  if (total === 0) return { top: [], scores: [] };

  const docTf = sentences.map(function (s) {
    const t = tokenize(s);
    const map = Object.create(null);
    for (const tk of t) map[tk] = (map[tk] || 0) + 1;
    return { tokens: t, map: map, len: t.length || 1 };
  });

  // 逆文档频率：词出现在几句中
  const df = Object.create(null);
  for (const d of docTf) {
    for (const k in d.map) {
      df[k] = (df[k] || 0) + 1;
    }
  }
  const nDocs = total;

  const scores = docTf.map(function (d, i) {
    let tfidf = 0;
    for (const k in d.map) {
      const tf = d.map[k] / d.len;
      const idf = Math.log((nDocs + 1) / ((df[k] || 0) + 1)) + 1;
      tfidf += tf * idf;
    }
    // 位置权重：首句/前几句信息密度最高
    const pos = 1 / (1 + 0.25 * i);
    // 长度惩罚：过短句(<8 token)降权
    const lenPenalty = d.len < 8 ? 0.6 : 1;
    // 信息加分：含数字、含风险词加权
    const numBonus = /\d/.test(sentences[i]) ? 0.15 : 0;
    const riskBonus = isRiskSentence(sentences[i]) ? 0.2 : 0;
    return { si: i, score: tfidf * pos * lenPenalty + numBonus + riskBonus };
  });

  const ranked = scores.slice().sort(function (a, b) {
    if (b.score !== a.score) return b.score - a.score;
    return a.si - b.si;
  });
  const chosen = ranked.slice(0, limit).sort(function (a, b) { return a.si - b.si; });
  return { top: chosen.map(function (c) { return { si: c.si, score: round(c.score, 4), sentence: sentences[c.si] }; }), scores: scores };
}

function round(n, d) {
  const f = Math.pow(10, d);
  return Math.round(n * f) / f;
}

// ===== 长文速读：5 种常见格式的结构化提取模板 =====
// 每种格式 = 命中信号（signals，用于识别）+ 字段提取器（用于按该格式的惯用结构抽取内容）。
// 全部为纯正则/字符串计算：同输入同输出，找不到就给空字段，绝不编造。
const FORMAT_DEFS = [
  {
    key: 'meeting', label: '会议纪要',
    signals: [/会议|纪要|议题|与会|参会|出席|例会|周会|站会|评审会/, /决议|决定|待办|行动项|跟进|负责|定稿/, /(\d{1,2}月\d{1,2}日|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|\d{1,2}[:：]\d{2})/]
  },
  {
    key: 'weekly', label: '工作周报',
    signals: [/本周|上周|周报/, /下周|计划|下一步|待办/, /完成|进展|交付|上线|推进/]
  },
  {
    key: 'academic', label: '学术摘要',
    signals: [/摘要|Abstract|关键词|Keywords/i, /研究|论文|实验|模型|方法|课题/, /结论|表明|验证|提升|优于|精度/]
  },
  {
    key: 'tech', label: '技术文档',
    signals: [/安装|部署|配置|依赖|环境|镜像/, /接口|参数|请求|响应|字段|函数|调用|示例|API|SDK|命令/i, /步骤|快速开始|使用说明|教程|README/i],
  },
  {
    key: 'news', label: '新闻资讯',
    signals: [/记者|报道|讯|获悉|据悉|消息称|通讯社/, /今日|昨日|日前|今天|昨天/, /表示|称|宣布|透露|指出|负责人/]
  }
];

// 格式识别：数信号命中数，最高分且 ≥2 才算该格式，否则归为通用长文。得分相同按声明顺序（确定性）。
function detectFormat(src) {
  let best = null, bestScore = 0;
  for (const def of FORMAT_DEFS) {
    let score = 0;
    for (const re of def.signals) {
      if (re.test(src)) score++;
    }
    if (score > bestScore) { best = def; bestScore = score; }
  }
  if (best && bestScore >= 2) return { key: best.key, label: best.label };
  return { key: 'general', label: '通用长文' };
}

function linesOf(src) {
  return src.split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
}

// 从若干句子里筛命中 re 的，截断后取前 n 条。
function pick(items, re, n) {
  const out = [];
  for (const s of items) {
    if (re.test(s)) { out.push(truncate(s, 60)); if (out.length >= n) break; }
  }
  return out;
}

function field(label, items) {
  return items && items.length ? { label: label, items: items } : null;
}

// 各格式字段抽取：meeting→时间/参会/决议/行动项；weekly→进展/进行中/计划/阻塞；
// academic→关键词/目的/方法/结果；tech→步骤/命令与接口/配置；news→时间/主体/事件。
function buildFormatFields(key, src, sentences) {
  const lines = linesOf(src);
  let fields = [];
  if (key === 'meeting') {
    const timeLine = lines.filter(function (l) { return /(\d{1,2}月\d{1,2}日|\d{1,2}[:：]\d{2})|周[一二三四五六日天]/.test(l); }).slice(0, 1);
    fields = [
      field('会议时间', timeLine.map(function (l) { return truncate(l, 40); })),
      field('参会人员', pick(lines, /参会|与会|出席|参加|人员[:：]/, 2).map(function (l) { const i = l.search(/[:：]/); return truncate(i >= 0 ? l.slice(i + 1) : l, 40); })),
      field('会议决议', pick(sentences, /决议|决定|通过|同意|确定|拍板/, 3)),
      field('行动项', pick(sentences, /负责|跟进|落实|之前|截止|deadline|待办|安排/, 3))
    ];
  } else if (key === 'weekly') {
    fields = [
      field('本周完成', pick(sentences, /完成|已上线|交付|达成|上线/, 3)),
      field('进行中', pick(sentences, /推进|正在|进行|调试|开发/, 3)),
      field('下周计划', pick(sentences, /下周|计划|下一步|待|将/, 3)),
      field('风险与阻塞', pick(sentences, /阻塞|风险|依赖|等待|问题|延期/, 3))
    ];
  } else if (key === 'academic') {
    let keywords = [];
    const kwLine = src.match(/(?:关键词|Keywords?)[\s:：]*(.+)/i);
    if (kwLine) keywords = kwLine[1].split(/[;；,，、\/]+/).map(function (k) { return k.trim(); }).filter(Boolean).slice(0, 6);
    fields = [
      field('关键词', keywords),
      field('研究目的', pick(sentences, /旨在|目的|为了|针对|解决/, 2)),
      field('方法', pick(sentences, /方法|提出|构建|设计|基于|采用|框架/, 2)),
      field('结果', pick(sentences, /实验|结果|提升|降低|达到|优于|精度|误差/, 2))
    ];
  } else if (key === 'tech') {
    fields = [
      field('操作步骤', lines.filter(function (l) { return /^(\d+[\.、)]|步骤\s*\d+|第[一二三四五六七八九十]+步|#{1,4}\s*\S)/.test(l); }).slice(0, 5).map(function (l) { return truncate(l.replace(/^#+\s*/, ''), 50); })),
      field('命令与接口', pick(lines, /(GET|POST|PUT|DELETE|PATCH)\s+\/|\$ |npm |pnpm |yarn |pip |docker |curl |kubectl /i, 4)),
      field('配置要点', pick(lines, /配置|参数|环境变量|端口|依赖|env|config|port/i, 3)),
      field('内容概述', sentences.length ? [truncate(sentences[0], 60)] : [])
    ];
  } else if (key === 'news') {
    const when = src.match(/\d{1,2}月\d{1,2}日(凌晨|上午|下午|晚上|消息)?|今日|昨日|日前/);
    const where = src.match(/([\u4e00-\u9fa5]{2,6})(?:市|省|州|区)[，,]?(讯|电|消息)/);
    fields = [
      field('时间', when ? [when[0]] : []),
      field('地点', where ? [where[1] + where[2].replace(/讯|电|消息/, '')] : []),
      field('相关方', pick(sentences, /表示|称|宣布|透露|指出|负责人|部门|公司|政府/, 2)),
      field('核心事件', sentences.length ? [truncate(sentences[0], 60)] : [])
    ];
  }
  return fields.filter(Boolean);
}

// ===== 快读：论文/财报/长文 → 一页纸 =====
function analyzeDocument(text, opts) {
  const o = opts || {};
  const maxSentences = o.maxSentences || 3;
  const src = normalizeInput(text);
  const sentences = splitSentences(src);

  const summaryResult = summarize(sentences, maxSentences);
  const keyData = extractKeyData(sentences);
  const risks = sentences
    .map(function (s, i) { return { sentence: s, si: i }; })
    .filter(function (x) { return isRiskSentence(x.sentence); })
    .slice(0, 3)
    .map(function (x) {
      const terms = [];
      for (const t of RISK_TERMS) {
        if (t === '好' || t === '增长' || t === '超预期') continue;
        if (x.sentence.indexOf(t) !== -1 && terms.indexOf(t) === -1) terms.push(t);
      }
      // 风险穿透：给每个风险句打上红线类型与严重度，未命中专项时归为通用风险信号
      const classes = classifyRiskSentence(x.sentence);
      const top = classes.length ? classes[0].def : null;
      return {
        text: truncate(x.sentence, 80),
        terms: terms,
        evidence: truncate(x.sentence, 120),
        si: x.si,
        category: top ? top.label : '风险信号',
        categoryKey: top ? top.key : 'general',
        severity: top ? top.severity : 'medium',
        playbook: classes.map(function (c) { return { key: c.def.key, label: c.def.label, severity: c.def.severity, matched: c.matched }; })
      };
    });

  const landscape = extractLandscape(sentences);

  // 风险红线警示卡：与 risks 一一对应，供页面按「类型 + 严重度 + 证据」渲染穿透卡
  const riskCards = risks.map(function (r, i) {
    return {
      id: 'rc_' + i + '_' + hashString(r.evidence),
      title: r.category,
      severity: r.severity,
      keywords: r.terms.slice(0, 4),
      detail: r.evidence,
      types: r.playbook.map(function (p) { return p.label; })
    };
  });

  const conclusionSource = summaryResult.top.length ? summaryResult.top[0].sentence : (sentences[0] || '');
  const conclusion = conclusionSource ? truncate(conclusionSource, 60) : '未检测到有效文本';

  // 引用依据：取摘要句作为可回溯证据
  const evidence = summaryResult.top.map(function (t) {
    return { text: truncate(t.sentence, 100), si: t.si };
  });

  // 格式识别 + 模板化字段抽取（会议纪要/周报/学术摘要/技术文档/新闻资讯/通用长文）
  const fmt = detectFormat(src);
  const formatFields = buildFormatFields(fmt.key, src, sentences);

  return {
    conclusion: conclusion,
    keyData: keyData,
    risks: risks,
    riskCards: riskCards,
    landscape: landscape,
    evidence: evidence,
    summary: truncate(conclusion, 120),
    sentenceCount: sentences.length,
    format: fmt.key,
    formatLabel: fmt.label,
    id: 'doc_' + hashString(src),
    // structured 供 demo / 页面统一渲染
    structured: {
      conclusion: conclusion,
      keyData: keyData,
      risks: risks,
      riskCards: riskCards,
      landscape: landscape,
      evidence: evidence,
      format: { key: fmt.key, label: fmt.label, fields: formatFields }
    }
  };
}

// ===== 日程断舍离 =====
const URGENT_TERMS = ['紧急', '今天', '明天', '尽快', '立刻', '马上', '截止', 'deadline', '急', '重要', '必须'];
const DEFER_TERMS = ['有空', '下周', '以后', '待定', '不急', '择期', '回头', '改天', '再说'];
const NOISE_TERMS = ['顺便', '也许', '可能', '看情况', '如果有空', '随便', '试试', '了解一下', '感兴趣'];
// 影响面关键词：命中越多分越高
const IMPACT_TERMS = ['发布', '上线', '评审', '汇报', '客户', '签约', '提案', '路演', '面试', '答辩', '上线', '提交', '截止', '会议', '演示'];

function scoreTask(line, now) {
  const tokens = tokenize(line);
  let urgent = 0, defer = 0, noise = 0, impact = 0;
  for (const t of URGENT_TERMS) if (line.indexOf(t) !== -1) urgent += 2;
  for (const t of DEFER_TERMS) if (line.indexOf(t) !== -1) defer += 2;
  for (const t of NOISE_TERMS) if (line.indexOf(t) !== -1) noise += 2;
  for (const t of IMPACT_TERMS) if (line.indexOf(t) !== -1) impact += 1;
  // 含明确时间点加分（确定性：只看字符串，不读系统时间）
  const hasTime = /\d{1,2}[:：]\d{2}|上午|下午|晚上|早上|\d+点|\d+月\d+日|周[一二三四五六日天]/.test(line);
  if (hasTime) urgent += 3;
  const score = urgent + impact * 2 - noise - defer;
  return { score: score, urgent: urgent, impact: impact, noise: noise, defer: defer, hasTime: hasTime };
}

function analyzeSchedule(text, opts) {
  const o = opts || {};
  // now：毫秒数或 Date；缺省用 epoch 0，确保无参调用也确定性
  const nowMs = typeof o.now === 'number' ? o.now : (o.now instanceof Date ? o.now.getTime() : 0);
  const src = normalizeInput(text);
  const lines = src.split('\n').map(function (l) { return l.replace(/^[\s\-•*·]+/, '').trim(); }).filter(Boolean);

  const scored = lines.map(function (l) { return { line: l, sc: scoreTask(l, nowMs) }; });

  const must = scored.filter(function (x) { return x.sc.score >= 3; }).sort(function (a, b) { return b.sc.score - a.sc.score; });
  const canDefer = scored.filter(function (x) { return x.sc.score >= 0 && x.sc.score < 3; });
  const deletions = scored.filter(function (x) { return x.sc.score < 0 || (x.sc.noise > 0 && x.sc.impact === 0 && x.sc.urgent === 0); });

  const top3 = must.slice(0, 3);

  // 时间块：09:00-22:00 按任务时长切；时长由影响面/紧急度推断（确定性）
  const blocks = buildTimeBlocks(top3.map(function (x) { return { line: x.line }; }), canDefer.slice(0, 2).map(function (x) { return { line: x.line }; }));

  const deletionOut = deletions.map(function (x) {
    return { item: x.line, reason: deletionReason(x.sc) };
  });

  return {
    today: top3.map(function (x) { return x.line; }),
    defer: canDefer.map(function (x) { return x.line; }),
    deletions: deletionOut,
    timeBlocks: blocks,
    summary: top3.length ? ('今日必做 ' + top3.length + ' 项') : '暂无高优先级事项',
    id: 'sch_' + hashString(src),
    structured: {
      today: top3.map(function (x) { return { text: x.line, score: round(x.sc.score, 2) }; }),
      defer: canDefer.map(function (x) { return x.line; }),
      deletions: deletionOut,
      timeBlocks: blocks
    }
  };
}

function deletionReason(sc) {
  if (sc.noise > 0) return '含犹豫/可选词，长期不做也不会产生后果';
  if (sc.impact === 0 && sc.urgent === 0) return '既无紧急信号也无影响面，删除后无连带损失';
  return '优先级显著低于其他事项，建议移除以免挤占注意力';
}

// 09:00-22:00 排时间块：must 在前段，defer 在后段，单块 60/90 分钟
function buildTimeBlocks(must, defer) {
  const blocks = [];
  let cursor = 9 * 60; // 分钟
  const end = 22 * 60;
  function fmt(min) {
    const h = Math.floor(min / 60), m = min % 60;
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  for (const t of must) {
    if (cursor >= end) break;
    const dur = 90;
    blocks.push({ start: fmt(cursor), end: fmt(Math.min(cursor + dur, end)), type: 'must', label: truncate(t.line, 24) });
    cursor += dur;
  }
  if (cursor < end) { blocks.push({ start: fmt(cursor), end: fmt(Math.min(cursor + 45, end)), type: 'break', label: '缓冲/休息' }); cursor += 45; }
  for (const t of defer) {
    if (cursor >= end) break;
    const dur = 60;
    blocks.push({ start: fmt(cursor), end: fmt(Math.min(cursor + dur, end)), type: 'defer', label: truncate(t.line, 24) });
    cursor += dur;
  }
  return blocks;
}

// 追问：基于已算出的 structured 上下文做确定性回答，不调模型。
function localAnswer(question, context) {
  const q = String(question || '').trim();
  if (!context) return '尚未产生分析结果，请先提交内容。';
  const structured = context.structured || context;
  const keys = Object.keys(structured);
  // 命中关键词回对应结构化块
  if (/护城河|壁垒|估值|下行/.test(q)) {
    const moatSeen = Object.create(null);
    const moatSrc = (structured.keyData || []).filter(function (d) {
      if (!/研发|营收|收入|利润|毛利|专利|增长|同比|环比/.test((d.label || '') + (d.evidence || ''))) return false;
      if (moatSeen[d.value]) return false;
      moatSeen[d.value] = true;
      return true;
    }).slice(0, 3);
    const cards = (structured.riskCards || []).slice();
    cards.sort(function (a, b) {
      const ra = SEVERITY_RANK[a.severity] || 0, rb = SEVERITY_RANK[b.severity] || 0;
      if (rb !== ra) return rb - ra;
      return String(a.id) < String(b.id) ? -1 : 1;
    });
    const downside = cards.slice(0, 3);
    const head = moatSrc.length
      ? '【护城河线索】以下量化信号来自原文，可作壁垒判断依据：\n' +
        moatSrc.map(function (d, i) { return (i + 1) + '. ' + d.value + '（' + d.label + '）'; }).join('\n')
      : '【护城河线索】原文未出现研发/营收/利润等可支撑壁垒判断的量化指标，不做无依据结论。';
    const tail = downside.length
      ? '\n【三大估值下行风险】按严重度排序：\n' +
        downside.map(function (c, i) { return (i + 1) + '. ' + c.title + '：' + c.detail; }).join('\n')
      : '\n【估值下行风险】未提取到红线风险信号。';
    return head + tail;
  }
  if (/竞争|格局|份额|龙头|行业/.test(q) && structured.landscape) {
    return structured.landscape.length
      ? '行业竞争格局（原文信号）：\n' + structured.landscape.map(function (l, i) {
          return (i + 1) + '. ' + l.text + '（命中：' + l.signals.join('、') + '）';
        }).join('\n')
      : '原文未出现份额/龙头/排名等竞争格局信号，无法给出格局对比。';
  }
  if (/风险|隐患|问题|坑/.test(q) && structured.risks) {
    return structured.risks.length
      ? '风险点：\n' + structured.risks.map(function (r, i) {
          const tag = r.category ? '〔' + r.category + '〕' : '';
          return (i + 1) + '. ' + tag + (r.text || r);
        }).join('\n')
      : '未发现明显风险信号。';
  }
  if (/数据|多少|指标|金额|数字/.test(q) && structured.keyData) {
    return structured.keyData.length
      ? '关键数据：\n' + structured.keyData.map(function (d, i) { return (i + 1) + '. ' + d.value + ' ' + d.label; }).join('\n')
      : '原文未出现可提取的数字指标。';
  }
  if (/删|去掉|移除/.test(q) && structured.deletions) {
    return structured.deletions.length
      ? '建议删除：\n' + structured.deletions.map(function (d, i) { return (i + 1) + '. ' + d.item + '（' + d.reason + '）'; }).join('\n')
      : '暂不建议删除任何事项。';
  }
  if (/今天|必做|top|优先/.test(q) && structured.today) {
    return structured.today.length
      ? '今日必做：\n' + structured.today.map(function (t, i) { return (i + 1) + '. ' + (t.text || t); }).join('\n')
      : '没有高优先级事项。';
  }
  if (/时间|安排|排|block/.test(q) && structured.timeBlocks) {
    return structured.timeBlocks.length
      ? '时间块：\n' + structured.timeBlocks.map(function (b) { return b.start + '-' + b.end + ' ' + b.label; }).join('\n')
      : '未生成时间块。';
  }
  if (/格式|类型|文体/.test(q) && structured.format && structured.format.label) {
    const f = structured.format;
    const lines = (f.fields || []).slice(0, 4).map(function (g) {
      return '· ' + g.label + '：' + g.items.join('；');
    });
    return '文体识别：「' + f.label + '」' + (lines.length ? '\n' + lines.join('\n') : '（该文本未命中此格式的专属字段）');
  }
  if (/结论|总结|一句话/.test(q)) return '结论：' + (structured.conclusion || structured.summary || '见一页纸正文。');
  return '基于当前结果可追问：风险、护城河与估值、竞争格局、数据、文体、结论、今日必做、时间块。（可用字段：' + keys.join('/') + '）';
}

// 闲聊兜底：与场景相关的确定性引导，绝不编造事实。
function localChat(question, scene) {
  if (scene === 'triage') {
    return '我可以帮你把杂乱待办拆成：今日必做 Top3、可延后、建议删除（含理由）与时间块。把待办贴进来即可。';
  }
  return '我可以把论文/财报/长文压成一页纸：一句话结论 + 关键财务指标徽章 + 风险红线穿透卡 + 行业竞争格局 + 原文引用依据，并自动识别会议纪要/周报/学术摘要/技术文档/新闻五种文体。粘贴文本或链接内容即可。';
}

module.exports = {
  analyzeDocument,
  analyzeSchedule,
  localAnswer,
  localChat,
  detectFormat
};
  });
  var api = {
    decode: __require('utils/decode.js'),
    cache: __require('utils/cache.js'),
    engine: __require('core/local-engine.js')
  };
  global.WA = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
