#!/usr/bin/env node
// H5 评委模拟器打包器：把小程序侧的纯逻辑模块（decode / local-engine / cache）
// 原样打进 web-sim/engine.bundle.js（IIFE + 微型 CommonJS 注册表）。
// 打包的是源码本体而非副本——引擎改了重跑一次即可，浏览器端行为与小程序端严格一致。
// 用法：node tools/build-h5-sim.js   （生成/更新 web-sim/engine.bundle.js）

'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

// 模块 id 用相对 src/ 的路径；require 说明符按 dirname 解析到这些 id
const MODULES = [
  'utils/decode.js',
  'utils/cache.js',
  'core/local-engine.js'
];

const VALID_IDS = new Set(MODULES);

function toId(srcRel, specifier) {
  const abs = path.resolve(path.dirname(path.join(ROOT, 'src', srcRel)), specifier);
  const rel = path.relative(path.join(ROOT, 'src'), abs).split(path.sep).join('/');
  const candidate = rel.endsWith('.js') ? rel : rel + '.js';
  if (!VALID_IDS.has(candidate)) {
    throw new Error('模块 ' + srcRel + ' 引用了未登记的内核文件：' + specifier);
  }
  return candidate;
}

// 只重写形如 require('...') 的字面量，保留其余源码一字不差
function rewriteRequires(srcRel, code) {
  return code.replace(/require\((['"])([^'"]+)\1\)/g, function (full, quote, specifier) {
    return "__require('" + toId(srcRel, specifier) + "')";
  });
}

const chunks = MODULES.map(function (id) {
  const code = fs.readFileSync(path.join(ROOT, 'src', id), 'utf8');
  return "  __def('" + id + "', function (module, exports, __require) {\n" +
    rewriteRequires(id, code) + "\n  });";
});

const banner = '// 自动生成，勿手改：node tools/build-h5-sim.js\n' +
  '// 源模块与小程序运行时共用同一份代码，保证同输入同输出的确定性行为一致。\n';

const bundle = banner +
  '(function (global) {\n' +
  "  var __registry = {};\n" +
  "  var __cache = {};\n" +
  '  function __def(id, fn) { __registry[id] = fn; }\n' +
  '  function __require(id) {\n' +
  '    if (__cache[id]) return __cache[id].exports;\n' +
  '    var mod = { exports: {} };\n' +
  '    __cache[id] = mod;\n' +
  '    __registry[id](mod, mod.exports, __require);\n' +
  '    return mod.exports;\n' +
  '  }\n' +
  chunks.join('\n') + '\n' +
  '  var api = {\n' +
  "    decode: __require('utils/decode.js'),\n" +
  "    cache: __require('utils/cache.js'),\n" +
  "    engine: __require('core/local-engine.js')\n" +
  '  };\n' +
  '  global.WA = api;\n' +
  "  if (typeof module !== 'undefined' && module.exports) module.exports = api;\n" +
  '})(typeof window !== "undefined" ? window : globalThis);\n';

const outDir = path.join(ROOT, 'web-sim');
fs.mkdirSync(outDir, { recursive: true });
const outFile = path.join(outDir, 'engine.bundle.js');
fs.writeFileSync(outFile, bundle, 'utf8');

// 打包完立刻在 Node 里自检一次：同一份 bundle 双端可跑，且输出确定性
const api = require(outFile);
const sample = '本季度实现营业收入 128.6 亿元，同比增长 23.4%。\n因质量问题被监管部门责令召回，涉及金额 1250 万元。';
const a = JSON.stringify(api.engine.analyzeDocument(sample, { maxSentences: 3 }));
const b = JSON.stringify(api.engine.analyzeDocument(sample, { maxSentences: 3 }));
if (a !== b) {
  console.error('✗ bundle 自检失败：同输入两次输出不一致');
  process.exit(1);
}

const kb = (fs.statSync(outFile).size / 1024).toFixed(1);
console.log('✓ web-sim/engine.bundle.js 已生成（' + kb + ' KB），双端确定性自检通过');
