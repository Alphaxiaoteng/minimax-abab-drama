// AI 适配器：实现 core/agent.js 消费的 ai 接口 { isAvailable, streamText, agentChat, cancel }。
// 铁律：任何异常（含同步抛错）一律转成 { ok:false, error }，绝不外抛，由上层 agent 降级 local-engine。
// 基础库版本探测：streamText 需 ≥3.15.1，bot agentChat 需 ≥3.7.1；版本不足 = 该能力不可用。
// 官方事实：streamText 参数包在 data 里；bot 的 eventStream 每条 event.data 为 JSON 字符串。

const config = require('../config.js');
const { parseAGUIEvent } = require('../utils/sse.js');

const STREAM_MIN_VERSION = '3.15.1';
const BOT_MIN_VERSION = '3.7.1';

function versionParts(v) {
  return String(v || '0.0.0').split('.').map(function (x) { return parseInt(x, 10) || 0; });
}

function versionGte(a, b) {
  const pa = versionParts(a);
  const pb = versionParts(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x > y;
  }
  return true;
}

function getWx() {
  return typeof globalThis !== 'undefined' && globalThis.wx ? globalThis.wx : null;
}

function getSdkVersion(wxObj) {
  try {
    if (wxObj && typeof wxObj.getAppBaseInfo === 'function') {
      const info = wxObj.getAppBaseInfo();
      if (info && info.SDKVersion) return info.SDKVersion;
    }
    if (wxObj && typeof wxObj.getSystemInfoSync === 'function') {
      const info = wxObj.getSystemInfoSync();
      if (info && info.SDKVersion) return info.SDKVersion;
    }
  } catch (e) {}
  return '0.0.0';
}

function errMsg(e) {
  return String((e && e.message) || e);
}

function createWxAIAdapter(opts) {
  const o = opts || {};
  const env = typeof o.env === 'string' ? o.env : config.CLOUD_ENV;
  const botId = typeof o.botId === 'string' ? o.botId : config.AGENT_BOT_ID;
  const model = o.model || config.MODEL;
  const clock = o.clock || { now: function () { return Date.now(); } };
  let cancelled = false;
  let cloudInited = false;

  // 空 env / 强制离线演示 / wx.cloud 缺失 → 整条 AI 链路不可用
  function coreReady() {
    if (config.IS_OFFLINE_DEMO) return false;
    if (!env) return false;
    const wxObj = getWx();
    if (!wxObj || !wxObj.cloud || !wxObj.cloud.extend || !wxObj.cloud.extend.AI) return false;
    return true;
  }

  function initCloud(wxObj) {
    if (cloudInited) return;
    if (typeof wxObj.cloud.init === 'function') wxObj.cloud.init({ env });
    cloudInited = true;
  }

  function isAvailable() {
    if (!coreReady()) return false;
    return versionGte(getSdkVersion(getWx()), BOT_MIN_VERSION);
  }

  async function streamText(params) {
    const p = params || {};
    const onText = typeof p.onText === 'function' ? p.onText : null;
    cancelled = false;
    const wxObj = getWx();
    if (!coreReady()) return { ok: false, mode: 'stream', text: '', error: 'AI_CORE_UNAVAILABLE' };
    if (!versionGte(getSdkVersion(wxObj), STREAM_MIN_VERSION)) {
      return { ok: false, mode: 'stream', text: '', error: 'BASE_LIB_LOW' };
    }
    let full = '';
    try {
      initCloud(wxObj);
      const provider = wxObj.cloud.extend.AI.createModel('cloudbase');
      const res = await provider.streamText({
        data: { model: p.model || model, messages: p.messages || [] }
      });
      for await (const chunk of res.textStream) {
        if (cancelled) break;
        const piece = typeof chunk === 'string' ? chunk : '';
        full += piece;
        if (onText) { try { onText(piece); } catch (e) {} }
      }
      return { ok: true, mode: 'stream', text: full, error: '' };
    } catch (e) {
      return { ok: false, mode: 'stream', text: full, error: errMsg(e) };
    }
  }

  // onEvent 收 { raw, parsed }：raw 为 event.data 原始字符串，parsed 为 parseAGUIEvent 结果
  async function agentChat(params) {
    const p = params || {};
    const onEvent = typeof p.onEvent === 'function' ? p.onEvent : null;
    cancelled = false;
    const id = p.botId || botId;
    const wxObj = getWx();
    if (!coreReady() || !id) return { ok: false, mode: 'bot', text: '', error: 'BOT_UNAVAILABLE' };
    if (!versionGte(getSdkVersion(wxObj), BOT_MIN_VERSION)) {
      return { ok: false, mode: 'bot', text: '', error: 'BASE_LIB_LOW' };
    }
    let text = '';
    try {
      initCloud(wxObj);
      const stamp = clock.now();
      const res = await wxObj.cloud.extend.AI.bot.sendMessage({
        data: {
          botId: id,
          threadId: p.threadId || ('thread_' + stamp),
          runId: p.runId || ('run_' + stamp),
          messages: p.messages || [],
          tools: [],
          context: [],
          state: {},
          forwardedProps: {}
        }
      });
      for await (const event of res.eventStream) {
        if (cancelled) break;
        const raw = event && typeof event.data === 'string'
          ? event.data
          : (typeof event === 'string' ? event : JSON.stringify(event || ''));
        const parsed = parseAGUIEvent(raw);
        if (parsed.type === 'TEXT_MESSAGE_CONTENT') text += parsed.delta;
        if (parsed.type === 'RUN_ERROR') {
          return { ok: false, mode: 'bot', text: text, error: parsed.message || 'RUN_ERROR' };
        }
        if (onEvent) { try { onEvent({ raw: raw, parsed: parsed }); } catch (e) {} }
      }
      return { ok: true, mode: 'bot', text: text, error: '' };
    } catch (e) {
      return { ok: false, mode: 'bot', text: text, error: errMsg(e) };
    }
  }

  function cancel() { cancelled = true; }

  return { isAvailable, streamText, agentChat, cancel };
}

// Mock 适配器：script 为流式文本块数组；latency 为块间等待 ms。fail=true 时所有能力不可用。
// 用于测试与离线演示；cancel 后当前流立即停止。
function createMockAIAdapter(opts) {
  const o = opts || {};
  const script = Array.isArray(o.script) ? o.script : ['模拟回答：这是一段用于离线演示的流式文本。'];
  const latency = typeof o.latency === 'number' ? o.latency : 10;
  let cancelled = false;
  let fail = !!o.fail;

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  return {
    isAvailable: function () { return !fail; },
    streamText: async function (params) {
      cancelled = false;
      if (fail) return { ok: false, mode: 'stream', text: '', error: 'MOCK_FAIL' };
      const onText = params && typeof params.onText === 'function' ? params.onText : null;
      let full = '';
      for (const piece of script) {
        if (cancelled) break;
        if (latency > 0) await sleep(latency);
        full += piece;
        if (onText) { try { onText(piece); } catch (e) {} }
      }
      return { ok: true, mode: 'stream', text: full, error: '' };
    },
    agentChat: async function (params) {
      cancelled = false;
      if (fail) return { ok: false, mode: 'bot', text: '', error: 'MOCK_FAIL' };
      const onEvent = params && typeof params.onEvent === 'function' ? params.onEvent : null;
      const events = [JSON.stringify({ type: 'RUN_STARTED' })];
      for (const piece of script) {
        events.push(JSON.stringify({ type: 'TEXT_MESSAGE_CONTENT', delta: piece }));
      }
      events.push(JSON.stringify({ type: 'RUN_FINISHED' }));
      let text = '';
      for (const raw of events) {
        if (cancelled) break;
        if (latency > 0) await sleep(latency);
        const parsed = parseAGUIEvent(raw);
        if (parsed.type === 'TEXT_MESSAGE_CONTENT') text += parsed.delta;
        if (onEvent) { try { onEvent({ raw: raw, parsed: parsed }); } catch (e) {} }
      }
      return { ok: true, mode: 'bot', text: text, error: '' };
    },
    cancel: function () { cancelled = true; },
    setFail: function (v) { fail = !!v; }
  };
}

module.exports = {
  createWxAIAdapter,
  createMockAIAdapter,
  versionGte,
  getSdkVersion,
  STREAM_MIN_VERSION,
  BOT_MIN_VERSION
};