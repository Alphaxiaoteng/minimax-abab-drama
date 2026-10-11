// 一页纸快读 · 详情页（分包 packages/quickread）。
// 职责：回放某条缓存的完整结构化结果 + 提供「追问」（agent.ask）+ 生成分享卡片。
// 追问优先走云开发 Agent 的多轮线程（threadId 保持在服务端），失败则用 localAnswer 兜底。

const config = require('../../../../config.js');
const { createAgent } = require('../../../../core/agent.js');
const { createWxAIAdapter } = require('../../../../core/ai-adapter.js');
const { buildShareCard, degradeToText } = require('../../../../share/card.js');

const app = getApp();

Page({
  data: {
    record: null,
    structured: null,
    offline: false,
    title: '',

    // 追问
    question: '',
    asking: false,
    answers: [],

    // 分享卡片
    shareCard: null,
    hasRecord: false
  },

  onLoad(options) {
    const id = options && options.id ? options.id : '';
    const cache = app.globalData && app.globalData.cache;
    let record = null;

    if (cache && id) {
      try { record = cache.get(id); } catch (e) { record = null; }
    }
    // 没带 id 或找不到时，退到最近一条，保证详情页永远有内容可看
    if (!record && cache) {
      try {
        const top = cache.rank().filter(function (r) { return r.scene === 'quickread'; });
        if (top.length) record = top[0];
      } catch (e) { record = null; }
    }

    const structured = record && record.meta ? record.meta.structured : null;
    const offline = !!(record && record.meta && record.meta.offline);

    this.setData({
      record: record,
      structured: structured || null,
      offline: offline,
      hasRecord: !!record,
      title: record ? record.title : '暂无记录'
    });

    if (structured) {
      this.setData({
        shareCard: buildShareCard({ scene: 'quickread', title: record.title, structured: structured })
      });
    }

    if (typeof wx.preloadSubpackage === 'function') {
      wx.preloadSubpackage({ name: 'triage', fail() {} });
    }
  },

  onQuestionInput(e) {
    this.setData({ question: e.detail.value || '' });
  },

  // 预设追问：点一下即填入并直接发问，降低评委操作成本
  onAskHint(e) {
    const q = e.currentTarget.dataset.q;
    if (!q) return;
    this.setData({ question: q });
    this.onAsk();
  },

  // 无记录时的空态行动：回到快读输入页（tabBar 页，用 switchTab）
  onOpenFirstScene() {
    wx.switchTab({ url: '/pages/quickread/index' });
  },

  // 追问：agent.ask 内部优先云端线程，失败回退 localAnswer，结果一定可见。
  async onAsk() {
    const q = String(this.data.question || '').trim();
    if (!q || this.data.asking) return;

    const structured = this.data.structured;
    if (!structured) {
      wx.showToast({ title: '暂无结果可追问', icon: 'none' });
      return;
    }

    this.setData({ asking: true });
    const answers = this.data.answers.slice();
    answers.push({ role: 'user', text: q });
    this.setData({ answers: answers, question: '' });

    let answerText = '';
    try {
      const ai = createWxAIAdapter({
        env: config.CLOUD_ENV,
        botId: config.AGENT_BOT_ID,
        model: config.MODEL
      });
      const agent = createAgent({ scene: 'quickread', ai: ai });
      const res = await agent.ask(q, {
        context: structured,
        onStep(evt) {
          if (evt && evt.kind === 'text') answerText += evt.text || '';
        }
      });
      if (res && res.text) answerText = res.text;
    } catch (e) {
      answerText = '';
    }

    if (!answerText) answerText = '未能获得回答，请稍后重试。';

    // 打字机式流式呈现：先挂空答复，再按帧增量 setData，模拟投研终端逐字输出
    const idx = this.data.answers.length;
    const shown = this.data.answers.concat([{ role: 'assistant', text: '', typing: true }]);
    this.setData({ answers: shown, asking: false });
    this.revealAnswer(idx, answerText);
  },

  revealAnswer(idx, full) {
    if (this._tw) clearInterval(this._tw);
    const step = Math.max(2, Math.ceil(full.length / 60));
    let pos = 0;
    this._tw = setInterval(() => {
      pos = Math.min(pos + step, full.length);
      const patch = {};
      patch['answers[' + idx + '].text'] = full.slice(0, pos);
      if (pos >= full.length) {
        patch['answers[' + idx + '].typing'] = false;
        clearInterval(this._tw);
        this._tw = null;
      }
      this.setData(patch);
    }, 30);
  },

  onUnload() {
    if (this._tw) {
      clearInterval(this._tw);
      this._tw = null;
    }
  },

  // 重新生成分享卡片（结果没变时直接用缓存的那份）
  onBuildCard() {
    const structured = this.data.structured;
    if (!structured) return;
    const card = buildShareCard({
      scene: 'quickread',
      title: this.data.title,
      structured: structured
    });
    this.setData({ shareCard: card });
    wx.showToast({ title: '卡片已就绪', icon: 'success' });
  },

  onCopyCard() {
    const structured = this.data.structured;
    if (!structured) return;
    const card = this.data.shareCard || buildShareCard({ scene: 'quickread', title: this.data.title, structured: structured });
    wx.setClipboardData({
      data: degradeToText(card),
      success() {
        wx.showToast({ title: '已复制分享文案', icon: 'success' });
      }
    });
  },

  // 分享：优先用结构化卡片生成的标题与摘要，保底纯文本。
  onShareAppMessage() {
    const structured = this.data.structured;
    const card = structured
      ? (this.data.shareCard || buildShareCard({ scene: 'quickread', title: this.data.title, structured: structured }))
      : null;

    return {
      title: card ? card.title + ' · ' + card.subtitle : 'AI 一页纸快读',
      path: '/pages/quickread/index' + (card ? '?' + card.query : '')
    };
  }
});
