// 一页纸快读 · 输入页（分包 packages/quickread）。
// 分工：本页只做「输入 + 触发 + 流式渲染」，结构化渲染交给 components/markdown-card。
//
// 关键决策：
//  - agent.run 首帧是骨架（立刻 setData，用户看到结构在动），随后才是流式文本；
//  - 流式 setData 做节流合并：模型每吐一个 token 就 setData 会打爆渲染层，
//    这里按「≥80ms 或累积 ≥48 字符」两个条件之一满足才 flush 一次；
//  - 任一失败（无云环境 / 版本不足 / 报错 / 超时）都静默降级到 local-engine，
//    结果照常渲染，只在结果区标注「离线分析」。

const config = require('../../config.js');
const { createAgent } = require('../../core/agent.js');
const { createStreamBus } = require('../../core/stream-bus.js');
const { buildSkeleton } = require('../../core/skeleton.js');
const { createWxAIAdapter } = require('../../core/ai-adapter.js');
const { normalizeInput } = require('../../utils/decode.js');

const app = getApp();

// 流式渲染节流阈值
const FLUSH_INTERVAL_MS = 80;
const FLUSH_CHARS = 48;

Page({
  data: {
    input: '',
    maxChars: config.MAX_INPUT_CHARS,
    inputChars: 0,
    running: false,

    // 骨架与流式
    steps: [],
    progress: 0,
    streamText: '',
    streaming: false,

    // 结构化结果
    structured: null,
    offline: false,
    elapsedMs: 0,
    modelName: 'local-engine',

    // 示例文本，方便评委一键体验
    sample: ''
  },

  onLoad() {
    // 预热另一个分包（triage），用户切 tab 时无下载等待。
    if (typeof wx.preloadSubpackage === 'function') {
      wx.preloadSubpackage({ name: 'triage', fail() {} });
    }
    this.bus = createStreamBus();
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

  // 一键填入示例长文（含明确数字，证明关键数据是真实抽取而非编造）
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

  // ===== 主流程 =====
  async onRun() {
    if (this.data.running) return;
    const text = normalizeInput(this.data.input);
    if (!text) {
      wx.showToast({ title: '请先粘贴内容', icon: 'none' });
      return;
    }

    // 骨架先行：立刻上屏，零等待
    const skeleton = buildSkeleton('quickread');
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

    // 订阅 bus：所有 agent 事件统一走这里，节流后一次性 setData
    this.unsubscribe = bus.on((evt) => this.consumeEvent(evt));

    const ai = createWxAIAdapter({
      env: config.CLOUD_ENV,
      botId: config.AGENT_BOT_ID,
      model: config.MODEL
    });
    this.agent = createAgent({ scene: 'quickread', ai: ai, bus: bus });

    let result = null;
    try {
      result = await this.agent.run(text, { onStep: (evt) => this.consumeEvent(evt) });
    } catch (e) {
      // agent 内部已兜底降级，这里只防御性处理
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

    // 记录这一笔：埋点 + 本地缓存（缓存是首页秒开的数据源）
    app.recordRun({ scene: 'quickread', ms: elapsedMs, mode: fallbackUsed ? 'local' : 'stream', ok: !!structured });
    this.persist(text, structured, fallbackUsed);
  },

  // 统一消费 agent 事件：骨架 / 步骤 / 文本（节流）
  consumeEvent(evt) {
    if (!evt || !evt.kind) return;

    if (evt.kind === 'skeleton' || evt.kind === 'step') {
      // 骨架事件：同步刷 steps，保证结构立即出现
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

  // 流式节流：时间或字符数任一达阈值即 flush，避免高频 setData。
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

  // 写入本地缓存：作为首页秒开的数据源；写入失败不影响结果展示。
  persist(text, structured, offline) {
    const cache = app.globalData && app.globalData.cache;
    if (!cache || !structured) return;
    try {
      const title = structured.conclusion || '一页纸快读';
      cache.put({
        id: 'qr_' + Date.now(),
        scene: 'quickread',
        title: String(title).slice(0, 24),
        summary: (structured.keyData || []).map(function (d) { return d.value; }).slice(0, 3).join(' · '),
        raw: text.slice(0, 4000),
        ts: Date.now(),
        hit: 0,
        score: (structured.keyData || []).length * 10 + (structured.risks || []).length * 6,
        tags: ['一页纸', offline ? '离线' : '云端'],
        meta: { offline: !!offline, structured: structured }
      });
      // 同步刷新首页 globalData，返回时首页 onShow 直接读到
      app.globalData.recentTop = cache.rank().slice(0, 8);
    } catch (e) {
      // 忽略缓存失败
    }
  },

  onOpenDetail() {
    const recent = this.data.structured;
    if (!recent) return;
    const cache = app.globalData && app.globalData.cache;
    let id = '';
    if (cache) {
      const list = cache.rank();
      if (list.length) id = list[0].id;
    }
    wx.navigateTo({ url: '/packages/quickread/pages/detail/index?id=' + id });
  },

  onOpenHistory() {
    wx.navigateTo({ url: '/packages/quickread/pages/history/index' });
  },

  buildSample() {
    return [
      '公司 2026 年第三季度经营情况说明',
      '本季度公司实现营业收入 128.6 亿元，同比增长 23.4%，环比增长 8.7%。',
      '归属于母公司股东的净利润为 15.7 亿元，同比增长 31.2%，净利率提升至 12.2%。',
      '毛利率为 38.1%，较去年同期提升 1.8 个百分点，主要来自高端产品占比提升。',
      '经营活动产生的现金流量净额为 22.3 亿元，同比增长 18.9%。',
      '研发投入 14.2 亿元，占营业收入比例 11.0%，同比增加 2.1 个百分点。',
      '海外业务收入 41.2 亿元，同比增长 26.5%，占总收入比重达到 32.0%。',
      '应收账款周转天数上升至 76 天，同比增加 9 天，需关注回款节奏放缓的风险。',
      '报告期内公司因产品质量问题被监管部门责令召回部分批次产品，涉及金额 1250 万元。',
      '同时公司面临原材料价格波动加剧与行业竞争加剧的压力，主要竞争对手已下调主力产品售价。',
      '公司预计第四季度收入增速将放缓至 15% 左右，并提示汇率波动可能带来汇兑损失。'
    ].join('\n');
  }
});
