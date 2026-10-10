// 离线确定性内核：无云环境/基础库过低/调用失败/超时时，agent 降级到这里，保证评委扫码也能完整跑通。
// 铁律：全部函数真实计算（TF-IDF×位置权重摘要、正则提数、词表匹配），禁止硬编码假数据；
// 同输入必须同输出——analyzeDocument 完全不读时间，analyzeSchedule 的时间相关项只由传入的 now 决定。

const { normalizeInput, splitSentences, tokenize, hashString, formatClock } = require('../utils/decode.js');

// 风险词表：命中即把整句列为风险点并附原文引用。词表可按财报/论文场景扩展。
const RISK_TERMS = [
  '下滑', '亏损', '诉讼', '监管', '违约', '召回', '延期', '竞争加剧', '减值', '商誉',
  '处罚', '违规', '退市', '降价', '裁员', '负债', '逾期', '造假', '不确定性',
  'decline', 'loss', 'lawsuit', 'regulation', 'default', 'recall', 'delay', 'impairment'
];

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
      return { text: truncate(x.sentence, 80), terms: terms, evidence: truncate(x.sentence, 120), si: x.si };
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
  if (/风险|隐患|问题|坑/.test(q) && structured.risks) {
    return structured.risks.length
      ? '风险点：\n' + structured.risks.map(function (r, i) { return (i + 1) + '. ' + (r.text || r); }).join('\n')
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
  return '基于当前结果可追问：风险、数据、文体、结论、今日必做、时间块。（可用字段：' + keys.join('/') + '）';
}

// 闲聊兜底：与场景相关的确定性引导，绝不编造事实。
function localChat(question, scene) {
  if (scene === 'triage') {
    return '我可以帮你把杂乱待办拆成：今日必做 Top3、可延后、建议删除（含理由）与时间块。把待办贴进来即可。';
  }
  return '我可以把论文/财报/长文压成一页纸：一句话结论 + 3 个关键数据 + 3 个风险点 + 原文引用依据，并自动识别会议纪要/周报/学术摘要/技术文档/新闻五种文体。粘贴文本或链接内容即可。';
}

module.exports = {
  analyzeDocument,
  analyzeSchedule,
  localAnswer,
  localChat,
  detectFormat
};