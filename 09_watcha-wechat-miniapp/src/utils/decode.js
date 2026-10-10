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