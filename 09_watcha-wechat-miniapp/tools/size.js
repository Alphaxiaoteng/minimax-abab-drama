#!/usr/bin/env node
'use strict';
// size.js —— 主包/分包体积统计（npm run size）
// 分组：主包（src 除 packages/ 外）/ packages/quickread / packages/triage / 其他分包。
// 输出表格 + 合计 + 相对 2MB 主包上限的占用百分比。
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const LIMIT_MAIN = 2 * 1024 * 1024;

function walk(dir, acc) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
  catch { return acc; }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, acc);
    else if (e.isFile()) acc.push(full);
  }
  return acc;
}

const groups = new Map(); // name -> {count, bytes}
function add(name, size) {
  const g = groups.get(name) || { count: 0, bytes: 0 };
  g.count++; g.bytes += size;
  groups.set(name, g);
}

if (!fs.existsSync(SRC)) {
  console.log('⚠ src/ 目录不存在：并行 agent 尚未生成源码，无体积可统计。');
  console.log('预期分组：主包 / packages/quickread / packages/triage / 其他');
  process.exitCode = 0;
} else {
  const files = walk(SRC, []);
  for (const f of files) {
    const rp = path.relative(SRC, f).split(path.sep).join('/');
    const size = fs.statSync(f).size;
    const m = rp.match(/^packages\/([^/]+)\//);
    if (m) add('packages/' + m[1], size);
    else add('主包', size);
  }
  const order = ['主包', 'packages/quickread', 'packages/triage'];
  const names = [...groups.keys()].sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
  });

  const fmt = (b) => b >= 1024 * 1024
    ? (b / 1024 / 1024).toFixed(2) + ' MB'
    : (b / 1024).toFixed(1) + ' KB';
  const pad = (s, w) => s + ' '.repeat(Math.max(0, w - s.length));

  console.log('===== 体积统计（src/）=====');
  console.log(pad('分组', 24) + pad('文件数', 8) + pad('字节数', 12) + '占比');
  console.log('-'.repeat(56));
  let totalBytes = 0;
  for (const n of names) {
    const g = groups.get(n);
    totalBytes += g.bytes;
  }
  for (const n of names) {
    const g = groups.get(n);
    const pct = ((g.bytes / totalBytes) * 100).toFixed(1) + '%';
    console.log(pad(n, 24) + pad(String(g.count), 8) + pad(fmt(g.bytes), 12) + pct);
  }
  console.log('-'.repeat(56));
  console.log(pad('合计', 24) + pad(String(files.length), 8) + pad(fmt(totalBytes), 12) + '100.0%');

  const main = groups.get('主包') || { bytes: 0 };
  const used = (main.bytes / LIMIT_MAIN) * 100;
  console.log(`\n主包占用 2MB 硬限：${used.toFixed(2)}%（${fmt(main.bytes)} / ${fmt(LIMIT_MAIN)}）`);
  for (const n of names) {
    if (n === '主包') continue;
    const g = groups.get(n);
    console.log(`分包 ${n}：${((g.bytes / LIMIT_MAIN) * 100).toFixed(2)}% / 2MB 上限`);
  }
  if (main.bytes > LIMIT_MAIN) {
    console.log('❌ 主包超过 2MB 硬限，请核对分包配置。');
    process.exitCode = 1;
  }
}