// 分享卡片：把结构化一页纸压成微信 onShareAppMessage 需要的 { title, path, query } 与可复制纯文本。
// 卡片 lines 全部来自已算出的 structured，不编造；degradeToText 用于 canvas 不可用时的保底文案。

// 卡片行定宽截断（card 本地工具，不外泄到 utils，避免新增契约外模块）
function truncate(s, n) {
  const str = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  return str.length <= n ? str : str.slice(0, n) + '…';
}

const HASHTAG = '#观猹AI一页纸';

function buildShareCard(opts) {
  const o = opts || {};
  const scene = o.scene || 'quickread';
  const structured = o.structured || {};
  const title = o.title || (scene === 'triage' ? '我的今日断舍离清单' : '我的一页纸快读');

  let lines;
  let subtitle;
  if (scene === 'triage') {
    const today = (structured.today || []).map(function (t) { return typeof t === 'string' ? t : t.text; });
    const dels = (structured.deletions || []).map(function (d) { return d.item; });
    lines = [];
    today.forEach(function (t, i) { lines.push((i + 1) + '. ' + truncate(t, 22)); });
    if (dels.length) lines.push('删：' + truncate(dels.join('、'), 30));
    subtitle = '今日必做 ' + today.length + ' 项';
  } else {
    const keyData = structured.keyData || [];
    const risks = structured.risks || [];
    lines = [];
    if (structured.conclusion) lines.push(truncate(structured.conclusion, 34));
    keyData.forEach(function (d) { lines.push('▪ ' + truncate(d.value + ' ' + d.label, 24)); });
    risks.forEach(function (r) { lines.push('⚠ ' + truncate(r.text, 24)); });
    subtitle = keyData.length + ' 个关键数据 · ' + risks.length + ' 个风险';
  }

  const query = 'scene=' + encodeURIComponent(scene) + '&title=' + encodeURIComponent(title) + '&from=share';

  return {
    title: title,
    subtitle: subtitle,
    lines: lines,
    hashtag: HASHTAG,
    query: query
  };
}

// 保底纯文本：canvas 绘制失败或旧客户端时，直接把卡片转成一段可分享文本。
function degradeToText(card) {
  const c = card || {};
  const parts = [];
  parts.push(c.title || 'AI 一页纸');
  if (c.lines && c.lines.length) parts.push(c.lines.join('\n'));
  parts.push(c.hashtag || HASHTAG);
  return parts.join('\n');
}

module.exports = { buildShareCard, degradeToText, HASHTAG };