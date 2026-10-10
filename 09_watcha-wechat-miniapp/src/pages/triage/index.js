// 日程断舍离 · 输入页（分包 packages/triage）。
// 与快读页共用同一套 Agent/骨架/流式机制，只是 scene 换成 triage，结构化字段不同。
// 关键决策同样在 quickread 页里写过：骨架先行 + 流式节流 + 静默降级。这里保持同一节奏。

const config = require('../../config.js');
const { createAgent } = require('../../core/agent.js');
const { createStreamBus } = require('../../core/stream-bus.js');
const { buildSkeleton } = require('../../core/skeleton.js');
const { createWxAIAdapter } = require('../../core/ai-adapter.js');
const { normalizeInput } = require('../../utils/decode.js');

const app = getApp();

const FLUSH_INTERVAL_MS = 80;
const FLUSH_CHARS = 48;

Page({
  data: {
    input: '',
    maxChars: config.MAX_INPUT_CHARS,
    inputChars: 0,
    running: false,

    steps: [],
    progress: 0,
    streamText: '',
    streaming: false,

    structured: null,
    offline: false,
    elapsedMs: 0,
    modelName: 'local-engine',

    sample: ''
  },

  onLoad() {
    // 预热快读分包，用户切 tab 时零下载等待。
    if (typeof wx.preloadSubpackage === 'function') {
      wx.preloadSubpackage({ name: 'quickread', fail() {} });
    }
    this.agent = null;
    this.pendingText = '';
    this.lastFlush = 0;
    this.flushTimer = null;
    this.setData({ sample: this.buildSample() });
  },

  onUnload() {
    this.abortRun();
    clearTimeout(this.flushTimer);
  },

  onUseSample() {
    this.setData({
      input: this.data.sample,
      inputChars: this.data.sample.length
    });
  },

  onInput(e) {
    const v = e.detail.value || '';
    this.setData({ input: v, inputChars: v.length });
  },

  onClear() {
    this.abortRun();
    this.setData({
      input: '',
      inputChars: 0,
      structured: null,
      streamText: '',
      steps: [],
      progress: 0,
      elapsedMs: 0
    });
  },

  async onRun() {
    if (this.data.running) return;
    const text = normalizeInput(this.data.input);
    if (!text) {
      wx.showToast({ title: '请先粘贴待办', icon: 'none' });
      return;
    }

    const skeleton = buildSkeleton('triage');
    this.pendingText = '';
    this.lastFlush = 0;
    this.setData({
      running: true,
      streaming: true,
      steps: skeleton.steps,
      progress: 0,
      streamText: '',
      structured: null,
      offline: false,
      elapsedMs: 0
    });

    const bus = createStreamBus();
    this.bus = bus;
    const t0 = Date.now();
    this.unsubscribe = bus.on((evt) => this.consumeEvent(evt));

    const ai = createWxAIAdapter({
      env: config.CLOUD_ENV,
      botId: config.AGENT_BOT_ID,
      model: config.MODEL
    });
    this.agent = createAgent({ scene: 'triage', ai: ai, bus: bus });

    let result = null;
    try {
      result = await this.agent.run(text, { onStep: (evt) => this.consumeEvent(evt) });
    } catch (e) {
      result = null;
    }

    this.flushStream(true);

    const elapsedMs = Date.now() - t0;
    const structured = result && result.structured ? result.structured : null;
    const fallbackUsed = !result || result.fallbackUsed !== false;

    this.setData({
      running: false,
      streaming: false,
      structured: structured,
      offline: fallbackUsed,
      elapsedMs: elapsedMs,
      modelName: result && result.usage ? result.usage.model : 'local-engine'
    });

    app.recordRun({ scene: 'triage', ms: elapsedMs, mode: fallbackUsed ? 'local' : 'stream', ok: !!structured });
    this.persist(text, structured, fallbackUsed);
  },

  consumeEvent(evt) {
    if (!evt || !evt.kind) return;

    if (evt.kind === 'skeleton' || evt.kind === 'step') {
      const sk = this.agent ? this.agent.getSkeleton() : null;
      if (sk) this.setData({ steps: sk.steps, progress: sk.progress });
      return;
    }

    if (evt.kind === 'skeleton_done') {
      const sk = this.agent ? this.agent.getSkeleton() : null;
      if (sk) this.setData({ steps: sk.steps, progress: 100 });
      return;
    }

    if (evt.kind === 'text') {
      this.pendingText += evt.text || '';
      this.maybeFlush();
    }
  },

  maybeFlush() {
    const now = Date.now();
    if (this.pendingText.length >= FLUSH_CHARS || now - this.lastFlush >= FLUSH_INTERVAL_MS) {
      this.flushStream(false);
      return;
    }
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.flushStream(false);
    }, FLUSH_INTERVAL_MS);
  },

  flushStream(final) {
    clearTimeout(this.flushTimer);
    this.flushTimer = null;
    this.lastFlush = Date.now();
    this.setData({
      streamText: this.pendingText,
      streaming: !final && this.data.running
    });
  },

  abortRun() {
    if (this.agent) {
      try { this.agent.abort(); } catch (e) {}
      this.agent = null;
    }
    if (this.unsubscribe) {
      try { this.unsubscribe(); } catch (e) {}
      this.unsubscribe = null;
    }
  },

  onAbort() {
    this.abortRun();
    this.setData({ running: false, streaming: false });
    wx.showToast({ title: '已中断', icon: 'none' });
  },

  persist(text, structured, offline) {
    const cache = app.globalData && app.globalData.cache;
    if (!cache || !structured) return;
    try {
      const today = structured.today || [];
      cache.put({
        id: 'tr_' + Date.now(),
        scene: 'triage',
        title: '今日必做 ' + today.length + ' 项',
        summary: today.slice(0, 2).map(function (t) { return t.text; }).join(' · '),
        raw: text.slice(0, 4000),
        ts: Date.now(),
        hit: 0,
        score: today.length * 10 + (structured.deletions || []).length * 8,
        tags: ['断舍离', offline ? '离线' : '云端'],
        meta: { offline: !!offline, structured: structured }
      });
      app.globalData.recentTop = cache.rank().slice(0, 8);
    } catch (e) {
      // 忽略缓存失败
    }
  },

  onOpenToday() {
    const cache = app.globalData && app.globalData.cache;
    let id = '';
    if (cache) {
      try {
        const list = cache.rank().filter(function (r) { return r.scene === 'triage'; });
        if (list.length) id = list[0].id;
      } catch (e) {}
    }
    wx.navigateTo({ url: '/packages/triage/pages/today/index?id=' + id });
  },

  buildSample() {
    return [
      '紧急：报名 10 月 17 日小程序大赛截止前提交材料',
      '明天上午 9:00 参加 Q4 战略复盘会',
      '下午 3:00 与设计师评审秒开骨架屏',
      '回复张总邮件',
      '晚上 8:00 健身房锻炼',
      '给妈妈打电话（每周重复）',
      '顺便清理手机相册',
      '有空了解一下 uni-app 和原生小程序的差异',
      '不急，改天研究竞品新发布的版本',
      '整理上周路演反馈并归档',
      '周末可能考虑重构缓存模块',
      '更新一下个人主页的头像',
      '准备下周三客户签约提案'
    ].join('\n');
  }
});