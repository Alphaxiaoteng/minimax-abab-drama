// Agent 编排：把 ai 适配器（云）与 local-engine（确定性降级）、骨架步骤、流式总线打通。
// 对外只暴露 run / ask / abort。绝不直接引用 wx —— 依赖注入 ai/clock/bus，Node 测试可跑同一份代码。
// 关键决策：
//  - 首帧必须是 skeleton：run 一进来就 installSkeleton 并 emit 骨架，先给界面「在动」的占位，再流式填文本。
//  - 降级：ai 不可用 / 同步抛错 / reject / 超时 / AI 文本无法解析成结构化 —— 任一命中都静默转 local-engine，
//    fallbackUsed:true，structured 一定非空，绝不让页面白屏。
//  - 追问走 bot 线程：ask 用 ai.agentChat（多轮靠 threadId），失败再退到 localAnswer，结果回灌页面。

const config = require('../config.js');
const {
  buildSkeleton,
  installSkeleton,
  fillSkeleton,
  completeSkeleton
} = require('./skeleton.js');
const { analyzeDocument, analyzeSchedule, localAnswer, localChat } = require('./local-engine.js');

// 用注入的 clock 取毫秒；无 clock 时退到 Date.now（仅测试外的兜底，生产由 app 传真实时钟）。
function nowOf(clock) {
  if (clock && typeof clock.now === 'function') return clock.now();
  return Date.now();
}

// 请求模型返回严格 JSON，便于解析成结构化一页纸；system 里钉死字段，减少跑偏。
function buildMessages(scene, input) {
  const schemaQuickread = '{"conclusion":"一句话结论","keyData":[{"value":"","label":""}],"risks":[{"text":"","terms":["关键词"]}],"evidence":[{"text":""}]}';
  const schemaTriage = '{"today":[{"text":""}],"defer":[""],"deletions":[{"item":"","reason":""}],"timeBlocks":[{"start":"","end":"","label":""}]}';
  const schema = scene === 'triage' ? schemaTriage : schemaQuickread;
  const role = scene === 'triage'
    ? '你是日程断舍离助手。把用户杂乱待办压成结构化结果，只输出 JSON，不要解释、不要代码块。'
    : '你是一页纸快读助手。把论文/财报/长文压成结构化一页纸，只输出 JSON，不要解释、不要代码块。';
  return [
    { role: 'system', content: role + ' 严格按此结构输出：' + schema },
    { role: 'user', content: String(input || '') }
  ];
}

// 从可能带 ```json 包裹 / 前后噪声的文本里抠出第一个完整 JSON 对象，返回 null 表示失败（触发降级）。
function parseStructured(rawText, scene) {
  if (!rawText) return null;
  let s = String(rawText).trim();
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) s = fence[1].trim();
  const start = s.indexOf('{');
  const end = s.lastIndexOf('}');
  if (start === -1 || end === -1 || end <= start) return null;
  let obj;
  try {
    obj = JSON.parse(s.slice(start, end + 1));
  } catch (e) {
    return null;
  }
  if (!obj || typeof obj !== 'object') return null;
  return scene === 'triage' ? normalizeTriage(obj) : normalizeQuickread(obj);
}

function normalizeQuickread(obj) {
  const keyData = Array.isArray(obj.keyData)
    ? obj.keyData.slice(0, 3).map(function (d) { return { value: String(d.value || d || ''), label: String(d.label || '关键数据') }; })
    : [];
  const risks = Array.isArray(obj.risks)
    ? obj.risks.slice(0, 3).map(function (r) { return { text: String(r.text || r || ''), terms: Array.isArray(r.terms) ? r.terms : [] }; })
    : [];
  const evidence = Array.isArray(obj.evidence)
    ? obj.evidence.slice(0, 3).map(function (e) { return { text: String(e.text || e || '') }; })
    : [];
  const conclusion = String(obj.conclusion || '');
  if (!conclusion && !keyData.length && !risks.length) return null; // 空壳 = 视为解析失败，降级
  return { conclusion: conclusion, keyData: keyData, risks: risks, evidence: evidence };
}

function normalizeTriage(obj) {
  const today = Array.isArray(obj.today)
    ? obj.today.slice(0, 3).map(function (t) { return { text: String(t.text || t || '') }; })
    : [];
  const defer = Array.isArray(obj.defer) ? obj.defer.map(function (x) { return String(x); }) : [];
  const deletions = Array.isArray(obj.deletions)
    ? obj.deletions.map(function (d) { return { item: String(d.item || d || ''), reason: String(d.reason || '优先级较低') }; })
    : [];
  const timeBlocks = Array.isArray(obj.timeBlocks)
    ? obj.timeBlocks.map(function (b) { return { start: String(b.start || ''), end: String(b.end || ''), label: String(b.label || ''), type: String(b.type || 'must') }; })
    : [];
  if (!today.length && !defer.length && !deletions.length) return null;
  return { today: today, defer: defer, deletions: deletions, timeBlocks: timeBlocks };
}

function createAgent(opts) {
  const o = opts || {};
  const scene = o.scene || 'quickread';
  const ai = o.ai || null;
  const bus = o.bus || null;
  const clock = o.clock || { now: function () { return Date.now(); } };
  const timeoutMs = typeof o.timeoutMs === 'number' ? o.timeoutMs : config.TIMEOUT_MS;

  // 追问线程：同一 agent 实例复用，云端凭 threadId 维持多轮历史。
  const threadId = 'thread_' + nowOf(clock) + '_' + Math.floor(Math.random() * 1e6).toString(36);
  let cancelled = false;
  let structuredOut = null;
  let stepsOut = [];

  function emit(evt) {
    const item = { kind: evt.kind, text: evt.text === undefined ? '' : String(evt.text), at: nowOf(clock) };
    stepsOut.push(item);
    if (bus) bus.emit(item);
    return item;
  }

  // 统一包一层 Promise，把适配器可能的「同步抛错」也变成 rejection，供上层 try/catch 降级。
  function callStreamText(params) {
    return Promise.resolve().then(function () { return ai.streamText(params); });
  }
  function callAgentChat(params) {
    return Promise.resolve().then(function () { return ai.agentChat(params); });
  }

  // 带超时的等待：命中超时先 ai.cancel()，再 reject，交由 run 捕获降级。
  function withTimeout(promise) {
    if (!timeoutMs || timeoutMs <= 0) return promise;
    let timer = null;
    const guard = new Promise(function (resolve, reject) {
      timer = setTimeout(function () { reject(new Error('TIMEOUT')); }, timeoutMs);
    });
    return Promise.race([promise, guard]).finally(function () { clearTimeout(timer); });
  }

  // ===== 本地确定性降级：填充骨架每个槽位，保证 structured 非空、结果真实 =====
  function runLocal(input) {
    const res = scene === 'triage'
      ? analyzeSchedule(input, { now: nowOf(clock) })
      : analyzeDocument(input, { maxSentences: 3 });
    structuredOut = res.structured;
    if (scene === 'triage') {
      fillSkeleton(thisAgent, 'today', structuredOut.today.map(function (t) { return t.text; }).join(' / '));
      fillSkeleton(thisAgent, 'defer', structuredOut.defer.join(' / '));
      fillSkeleton(thisAgent, 'delete', structuredOut.deletions.map(function (d) { return d.item; }).join(' / '));
      fillSkeleton(thisAgent, 'blocks', structuredOut.timeBlocks.map(function (b) { return b.start + '-' + b.end; }).join(' / '));
    } else {
      fillSkeleton(thisAgent, 'conclusion', structuredOut.conclusion);
      fillSkeleton(thisAgent, 'data', structuredOut.keyData.map(function (d) { return d.value + ' ' + d.label; }).join(' / '));
      fillSkeleton(thisAgent, 'risk', structuredOut.risks.map(function (r) { return r.text; }).join(' / '));
      fillSkeleton(thisAgent, 'evidence', structuredOut.evidence.map(function (e) { return e.text; }).join(' / '));
    }
    completeSkeleton(thisAgent);
    emit({ kind: 'text', text: structuredOut.conclusion || structuredOut.today && structuredOut.today[0] && structuredOut.today[0].text || '' });
    return res;
  }

  // ===== 主入口 =====
  async function run(input, options) {
    const opt = options || {};
    const onStep = typeof opt.onStep === 'function' ? opt.onStep : null;
    const signal = opt.signal || null;

    if (bus) bus.reset();
    cancelled = false;
    stepsOut = [];
    structuredOut = null;
    const started = nowOf(clock);
    let mode = 'local';
    let usedModel = 'local-engine';
    let fallbackUsed = false;

    // 骨架先行：installSkeleton 会把骨架挂到 thisAgent._skeleton 并 emit 每步占位。
    installSkeleton(thisAgent, scene);
    if (onStep) { for (const st of stepsOut.slice()) onStep(st); }

    const aiOk = !!(ai && typeof ai.isAvailable === 'function' && ai.isAvailable());
    let text = '';
    let parsed = null;

    if (aiOk) {
      mode = 'stream';
      usedModel = config.MODEL;
      const messages = buildMessages(scene, input);
      try {
        const res = await withTimeout(callStreamText({
          model: config.MODEL,
          messages: messages,
          onText: function (piece) {
            text += piece;
            const evt = emit({ kind: 'text', text: piece });
            if (onStep) onStep(evt);
            if (signal && signal.cancelled) { cancelled = true; if (ai.cancel) ai.cancel(); }
          }
        }));
        if (res && res.ok) {
          if (!text) text = res.text || '';
          parsed = parseStructured(text, scene);
        } else {
          // 适配器已吞异常，用 ok:false 告知上层降级
          parsed = null;
        }
      } catch (e) {
        parsed = null; // 超时 / 抛错 → 降级
      }
    }

    // 解析失败或 ai 不可用 → 确定性本地内核，保证有结构化结果
    if (!parsed) {
      fallbackUsed = true;
      mode = 'local';
      usedModel = 'local-engine';
      const local = runLocal(input);
      text = local.summary || text;
      parsed = local.structured;
    } else {
      structuredOut = parsed;
      if (!bus || true) {
        // AI 成功路径：文本是原始 JSON，补一条纯文本结论给 stream-lines 兜底展示
        emit({ kind: 'conclusion', text: parsed.conclusion || '' });
      }
      completeSkeleton(thisAgent);
    }

    if (bus) bus.finalize();
    const usage = { mode: mode, ms: nowOf(clock) - started, model: usedModel };
    return { text: text, structured: parsed, steps: stepsOut.slice(), usage: usage, fallbackUsed: fallbackUsed };
  }

  // ===== 追问：优先云 Agent 多轮流式，失败退 localAnswer，全程通过 onStep 回流式文本 =====
  async function ask(question, options) {
    const opt = options || {};
    const onStep = typeof opt.onStep === 'function' ? opt.onStep : null;
    const q = String(question || '').trim();
    if (!q) return { text: '', fallbackUsed: false };

    const aiOk = !!(ai && typeof ai.isAvailable === 'function' && ai.isAvailable() && typeof ai.agentChat === 'function');
    if (aiOk && config.AGENT_BOT_ID) {
      let answer = '';
      try {
        const res = await withTimeout(callAgentChat({
          botId: config.AGENT_BOT_ID,
          threadId: threadId,
          runId: 'run_' + nowOf(clock),
          messages: [{ id: String(nowOf(clock)), role: 'user', content: q }],
          onEvent: function (env) {
            if (env && env.parsed && env.parsed.type === 'TEXT_MESSAGE_CONTENT' && env.parsed.delta) {
              answer += env.parsed.delta;
              if (onStep) onStep({ kind: 'text', text: env.parsed.delta, at: nowOf(clock) });
            }
          }
        }));
        if (res && res.ok && answer) return { text: answer, fallbackUsed: false };
        if (res && res.ok && res.text) return { text: res.text, fallbackUsed: false };
      } catch (e) { /* 降级 */ }
    }

    // 本地追问：确定性，基于已算出的 structured 上下文
    const fallbackText = structuredOut ? localAnswer(q, { structured: structuredOut }) : localChat(q, scene);
    if (onStep) onStep({ kind: 'text', text: fallbackText, at: nowOf(clock) });
    return { text: fallbackText, fallbackUsed: true };
  }

  function abort() {
    cancelled = true;
    if (ai && typeof ai.cancel === 'function') { try { ai.cancel(); } catch (e) {} }
  }

  const thisAgent = {
    scene: scene,
    emit: emit,
    getSteps: function () { return stepsOut.slice(); },
    getSkeleton: function () { return thisAgent._skeleton || buildSkeleton(scene); },
    run: run,
    ask: ask,
    abort: abort,
    _skeleton: null,
    _threadId: threadId
  };
  return thisAgent;
}

module.exports = { createAgent, parseStructured, buildMessages };