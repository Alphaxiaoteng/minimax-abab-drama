// 一页纸快读 · 历史记录（分包 packages/quickread）。
// 全部数据来自本地缓存（同步读 + search），不做网络请求，保证列表即时可用。

const app = getApp();

Page({
  data: {
    keyword: '',
    list: [],
    stats: null
  },

  onShow() {
    this.reload();
  },

  // 同步读缓存；search 为空时退化为 rank（按 score/ts 排序）。
  reload() {
    const cache = app.globalData && app.globalData.cache;
    if (!cache) {
      this.setData({ list: [], stats: null });
      return;
    }
    let list = [];
    let stats = null;
    const kw = String(this.data.keyword || '').trim();
    try {
      list = kw ? cache.search(kw) : cache.rank();
      list = list.filter(function (r) { return r.scene === 'quickread'; });
      stats = cache.stats();
    } catch (e) {
      list = [];
    }
    this.setData({ list: list, stats: stats });
  },

  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value || '' });
    this.reload();
  },

  onClearKeyword() {
    this.setData({ keyword: '' });
    this.reload();
  },

  onOpenItem(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({ url: '/packages/quickread/pages/detail/index?id=' + id });
  },

  onRemoveItem(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    const cache = app.globalData && app.globalData.cache;
    wx.showModal({
      title: '删除这条记录',
      content: '删除后无法恢复。',
      success: (res) => {
        if (!res.confirm || !cache) return;
        try { cache.remove(id); } catch (e) {}
        if (app.globalData) {
          try { app.globalData.recentTop = cache.rank().slice(0, 8); } catch (e) {}
        }
        this.reload();
      }
    });
  },

  onOpenFirstScene() {
    wx.navigateTo({ url: '/packages/quickread/pages/index/index' });
  },

  onClearAll() {
    const cache = app.globalData && app.globalData.cache;
    if (!cache) return;
    wx.showModal({
      title: '清空全部记录',
      content: '将删除本机保存的所有分析与历史记录。',
      success: (res) => {
        if (!res.confirm) return;
        try { cache.clear(); } catch (e) {}
        if (app.globalData) app.globalData.recentTop = [];
        this.reload();
      }
    });
  },

  onShareAppMessage() {
    return {
      title: '我的 AI 一页纸快读记录',
      path: '/packages/quickread/pages/index/index'
    };
  }
});
