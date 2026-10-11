// 日程断舍离 · 今日安排（分包 packages/triage）。
// 职责：回放最近一次断舍离结果，突出「今日必做 Top3 + 时间块」，并支持追问为什么这么排。
// 数据全部来自本地缓存（同步读），页面进入即有内容，符合秒开策略。

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
    hasRecord: false,
    title: '',

    // 顶部概览（本地算，不走网络）
    mustCount: 0,
    deferCount: 0,
    dropCount: 0,

    question: '',
    asking: false,
    answers: []
  },

  onLoad(options) {
    const id = options && options.id ? options.id : '';
    const cache = app.globalData && app.globalData.cache;
    let record = null;

    if (cache && id) {
      try { record = cache.get(id); } catch (e) { record = null; }
    }
    if (!record && cache) {
      try {
        const top = cache.rank().filter(function (r) { return r.scene === 'triage'; });
        if (top.length) record = top[0];
      } catch (e) { record = null; }
    }

    const structured = record && record.meta ? record.meta.structured : null;

    this.setData({
      record: record,
      structured: structured || null,
      hasRecord: !!record,
      offline: !!(record && record.meta && record.meta.offline),
      title: record ? record.title : '暂无安排',
      mustCount: structured && structured.today ? structured.today.length : 0,
      deferCount: structured && structured.defer ? structured.defer.length : 0,
      dropCount: structured && structured.deletions ? structured.deletions.length : 0
    });

    if (typeof wx.preloadSubpackage === 'function') {
      wx.preloadSubpackage({ name: 'quickread', fail() {} });
    }
  },

  onQuestionInput(e) {
    this.setData({ question: e.detail.value || '' });
  },

  onAskHint(e) {
    const q = e.currentTarget.dataset.q;
    if (!q) return;
    this.setData({ question: q });
    this.onAsk();
  },

  // 追问排程理由：云端线程优先，失败回退 localAnswer，保证界面一定有回应。
  async onAsk() {
    const q = String(this.data.question || '').trim();
    if (!q || this.data.asking) return;

    const structured = this.data.structured;
    if (!structured) {
      wx.showToast({ title: '暂无安排可追问', icon: 'none' });
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
      const agent = createAgent({ scene: 'triage', ai: ai });
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

    // 打字机式流式呈现：先挂空答复，再按帧增量 setData
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

  // 把 Top3 + 删除建议转成一段可分享文本
  onCopyPlan() {
    const structured = this.data.structured;
    if (!structured) return;
    const card = buildShareCard({ scene: 'triage', title: this.data.title, structured: structured });
    wx.setClipboardData({
      data: degradeToText(card),
      success() {
        wx.showToast({ title: '已复制今日安排', icon: 'success' });
      }
    });
  },

  onBackToInput() {
    wx.switchTab({ url: '/pages/triage/index' });
  },

  onShareAppMessage() {
    const structured = this.data.structured;
    const card = structured
      ? buildShareCard({ scene: 'triage', title: this.data.title, structured: structured })
      : null;
    return {
      title: card ? card.title + ' · ' + card.subtitle : '今日断舍离安排',
      path: '/pages/triage/index'
    };
  }
});