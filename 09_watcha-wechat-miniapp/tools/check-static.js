#!/usr/bin/env node
'use strict';
// check-static.js —— 赛事交付物「一键静态校验」
// 仅用 Node 内置模块，退出码 0/1，输出人类可读中文 PASS/FAIL 报告。
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const FOUR = ['.js', '.json', '.wxml', '.wxss'];
const TEXT_EXT = new Set(['.js', '.json', '.wxml', '.wxss']);
const LIMIT_MAIN = 2 * 1024 * 1024;   // 微信主包硬限 2MB
const LIMIT_PKG = 2 * 1024 * 1024;    // 单个分包硬限 2MB
const LIMIT_TOTAL = 20 * 1024 * 1024; // 整包软上限 20MB

let filesScanned = 0;
const failures = [];
const ruleReports = [];

function fail(rule, detail) {
  failures.push({ rule, detail });
}
function readJson(p) {
  const raw = fs.readFileSync(p, 'utf8');
  return JSON.parse(raw);
}
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
const rel = (p) => path.relative(SRC, p).split(path.sep).join('/');

// --- 收集文件 ---
const allFiles = fs.existsSync(SRC) ? walk(SRC, []) : [];
filesScanned = allFiles.length;
const byExt = {};
for (const f of allFiles) {
  const ext = path.extname(f);
  (byExt[ext] || (byExt[ext] = [])).push(f);
}
const appJsonPath = path.join(SRC, 'app.json');

// ===================== 规则 (a) app.json + 页面/分包四件套 =====================
function ruleA() {
  const r = '(a) app.json 合法 + 页面/分包四件套齐全';
  if (!fs.existsSync(appJsonPath)) { fail(r, 'src/app.json 不存在'); ruleReports.push([r, 0, 1]); return null; }
  let app;
  try { app = readJson(appJsonPath); }
  catch (e) { fail(r, 'app.json JSON 解析失败: ' + e.message); ruleReports.push([r, 0, 1]); return null; }
  let ok = 0, bad = 0;
  const pagePaths = [];
  (app.pages || []).forEach(p => pagePaths.push({ full: p, from: '主包 pages' }));
  (app.subPackages || []).forEach(sp => {
    if (!sp.root) { fail(r, 'subPackages 缺少 root'); bad++; return; }
    (sp.pages || []).forEach(p => pagePaths.push({ full: sp.root.replace(/\/$/, '') + '/' + p, from: '分包 ' + sp.root }));
  });
  pagePaths.forEach(({ full, from }) => {
    let missing = [];
    for (const ext of FOUR) {
      const base = path.isAbsolute(full) ? path.join(SRC, full) : path.join(SRC, full);
      if (!fs.existsSync(base + ext)) missing.push(ext);
    }
    if (missing.length) { fail(r, `${from} 页面 ${full} 缺 ${missing.join(',')}`); bad++; }
    else ok++;
  });
  ruleReports.push([r, ok, bad]);
  return app;
}

// ===================== 规则 (b) 页面/组件 .json 合法 + usingComponents 可解析 =====================
function ruleB() {
  const r = '(b) .json 合法 + usingComponents 解析到组件四件套';
  let ok = 0, bad = 0;
  for (const f of byExt['.json'] || []) {
    if (path.basename(f) === 'app.json') continue;
    let obj;
    try { obj = readJson(f); }
    catch (e) { fail(r, `${rel(f)} JSON 解析失败: ${e.message}`); bad++; continue; }
    const uc = obj.usingComponents;
    if (uc && typeof uc === 'object') {
      for (const [name, target] of Object.entries(uc)) {
        if (typeof target !== 'string') { fail(r, `${rel(f)} usingComponents.${name} 非字符串`); bad++; continue; }
        const base = target.startsWith('/')
          ? path.join(SRC, target)
          : path.join(path.dirname(f), target);
        const miss = FOUR.filter(ext => !fs.existsSync(base + ext));
        if (miss.length) { fail(r, `${rel(f)} 组件 ${name}->${target} 缺 ${miss.join(',')}`); bad++; }
        else ok++;
      }
    } else { ok++; }
  }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (c) wxml 事件名在 js 中有同名函数 =====================
function ruleC() {
  const r = '(c) wxml 事件名在 js 中存在同名函数';
  let ok = 0, bad = 0;
  for (const wf of byExt['.wxml'] || []) {
    const js = wf.replace(/\.wxml$/, '.js');
    if (!fs.existsSync(js)) { fail(r, `${rel(wf)} 同级 .js 不存在`); bad++; continue; }
    const wxml = fs.readFileSync(wf, 'utf8');
    const jsText = fs.readFileSync(js, 'utf8');
    const evRe = /(?:bind|catch)[:a-zA-Z]*\s*=\s*"([^"{}]+)"/g;
    let m; const names = new Set();
    while ((m = evRe.exec(wxml))) names.add(m[1].trim());
    for (const nm of names) {
      if (!nm) continue;
      const defRe = new RegExp('(?:[\\s,{]|^)' + nm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*(?:\\(|:|=(?:\\s*(?:async)?\\s*(?:function|\\())?)');
      if (defRe.test(jsText)) ok++;
      else { fail(r, `${rel(wf)} 事件 ${nm}() 在 ${rel(js)} 未定义`); bad++; }
    }
  }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (d) js require 相对路径可解析 =====================
function ruleD() {
  const r = '(d) js 相对 require 可解析';
  let ok = 0, bad = 0;
  for (const jf of byExt['.js'] || []) {
    const txt = fs.readFileSync(jf, 'utf8');
    const re = /require\(\s*['"]([^'"]+)['"]\s*\)/g;
    let m;
    while ((m = re.exec(txt))) {
      const p = m[1];
      if (!p.startsWith('.')) continue; // 只校验相对路径
      const dir = path.dirname(jf);
      const cand = [p, p + '.js', path.join(p, 'index.js')].map(c => path.resolve(dir, c));
      if (cand.some(c => fs.existsSync(c) && fs.statSync(c).isFile())) ok++;
      else { fail(r, `${rel(jf)} require('${p}') 无法解析`); bad++; }
    }
  }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (e) app.json 必含 lazyCodeLoading + networkTimeout.request =====================
function ruleE(app) {
  const r = '(e) lazyCodeLoading=requiredComponents + networkTimeout.request';
  if (!app) { fail(r, 'app.json 缺失，无法校验'); ruleReports.push([r, 0, 1]); return; }
  let ok = 0, bad = 0;
  if (app.lazyCodeLoading === 'requiredComponents') ok++;
  else { fail(r, `lazyCodeLoading=${JSON.stringify(app.lazyCodeLoading)}（需 "requiredComponents"）`); bad++; }
  const nt = app.networkTimeout && app.networkTimeout.request;
  if (typeof nt === 'number' && nt > 0) ok++;
  else { fail(r, `networkTimeout.request 缺失或非正数：${JSON.stringify(nt)}`); bad++; }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (f) 分包体积预检 =====================
function ruleF() {
  const r = '(f) 主包/分包体积预检';
  let mainBytes = 0; const pkgBytes = {};
  for (const f of allFiles) {
    const size = fs.statSync(f).size;
    const rp = rel(f);
    const m = rp.match(/^packages\/([^/]+)\//);
    if (m) pkgBytes[m[1]] = (pkgBytes[m[1]] || 0) + size;
    else mainBytes += size;
  }
  let ok = 0, bad = 0;
  const fmt = (b) => (b / 1024).toFixed(1) + ' KB';
  if (mainBytes > LIMIT_MAIN) { fail(r, `主包 ${fmt(mainBytes)} 超 2MB 硬限`); bad++; } else ok++;
  for (const [k, b] of Object.entries(pkgBytes)) {
    if (b > LIMIT_PKG) { fail(r, `分包 ${k} ${fmt(b)} 超 2MB 硬限`); bad++; } else ok++;
  }
  const total = mainBytes + Object.values(pkgBytes).reduce((a, c) => a + c, 0);
  if (total > LIMIT_TOTAL) { fail(r, `整包 ${fmt(total)} 超 20MB`); bad++; } else ok++;
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (g) 禁用未完成标记 + debugger =====================
function ruleG() {
  const r = '(g) 无 TODO/FIXME/占位/placeholder/debugger';
  // WXML 的 placeholder= 是官方输入框属性，不是未完成标记，必须豁免；只有裸写的 placeholder 标识符才算。
  const markerRe = /\b(TODO|FIXME|占位)\b|debugger|\bplaceholder\b(?!["']?\s*[:=])/i;
  let ok = 0, bad = 0;
  for (const f of allFiles) {
    if (!TEXT_EXT.has(path.extname(f))) continue;
    const lines = fs.readFileSync(f, 'utf8').split('\n');
    lines.forEach((ln, i) => {
      if (markerRe.test(ln)) { fail(r, `${rel(f)}:${i + 1} 命中禁用标记: ${ln.trim().slice(0, 60)}`); bad++; }
      else ok++;
    });
  }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (h) wxml 禁用 => / ?. / 反引号 =====================
function ruleH() {
  const r = '(h) wxml 无 =>/?. / 反引号';
  let ok = 0, bad = 0;
  for (const f of byExt['.wxml'] || []) {
    const lines = fs.readFileSync(f, 'utf8').split('\n');
    lines.forEach((ln, i) => {
      const hits = [];
      if (ln.includes('=>')) hits.push('=>');
      if (ln.includes('?.')) hits.push('?.');
      if (ln.includes('`')) hits.push('反引号');
      if (hits.length) { fail(r, `${rel(f)}:${i + 1} 含 ${hits.join(',')}`); bad++; }
      else ok++;
    });
  }
  ruleReports.push([r, ok, bad]);
}

// ===================== 规则 (i) tabBar 不得引用 iconPath =====================
function ruleI(app) {
  const r = '(i) tabBar 项不含 iconPath';
  if (!app) { fail(r, 'app.json 缺失'); ruleReports.push([r, 0, 1]); return; }
  let ok = 0, bad = 0;
  const list = app.tabBar && app.tabBar.list || [];
  for (const it of list) {
    if ('iconPath' in it || 'selectedIconPath' in it) { fail(r, `tabBar "${it.text || it.pagePath}" 引用 iconPath`); bad++; }
    else ok++;
  }
  if (!list.length) { fail(r, 'tabBar.list 缺失'); bad++; }
  ruleReports.push([r, ok, bad]);
}

// --- 执行 ---
const app = ruleA();
ruleB();
ruleC();
ruleD();
ruleE(app);
ruleF();
ruleG();
ruleH();
ruleI(app);

// --- 输出 ---
console.log('===== 静态校验报告（赛事交付物）=====');
if (!fs.existsSync(SRC)) console.log('⚠ src/ 目录不存在：并行 agent 尚未生成，本次校验为预期失败。');
for (const [rule, ok, bad] of ruleReports) {
  console.log(`${bad === 0 ? 'PASS' : 'FAIL'}  ${rule}  ✔${ok} ✘${bad}`);
}
if (failures.length) {
  console.log('\n--- 失败明细 ---');
  const grouped = {};
  failures.forEach(f => (grouped[f.rule] || (grouped[f.rule] = [])).push(f.detail));
  for (const [rule, ds] of Object.entries(grouped)) {
    console.log(`\n[${rule}]`);
    ds.slice(0, 30).forEach(d => console.log('  - ' + d));
    if (ds.length > 30) console.log(`  … 其余 ${ds.length - 30} 条`);
  }
}
process.exitCode = failures.length ? 1 : 0;
console.log(`\nchecked ${filesScanned} files, ${ruleReports.length} rules, ${failures.length} failures`);