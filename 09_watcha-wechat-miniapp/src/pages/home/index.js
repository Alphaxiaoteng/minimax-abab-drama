// 首页：秒开首屏。这是全站唯一的启动页，也是「秒开」这一核心卖点的证据现场。
//
// 秒开路径（onLoad 内全部同步，零网络、零 await）：
//   1) app.onLaunch 已同步预热缓存 → 这里直接读 globalData.recentTop；
//   2) 立刻 setData 渲染缓存命中的最近记录 + 骨架卡片；
//   3) 记录 firstRender 打点，写入 telemetry，页面顶部如实展示「首屏 X ms」。
// AI 刷新被刻意推迟到 onReady 之后，且失败时静默保持缓存内容，绝不白屏。

const app = getApp();

Page({
  data: {
    // ---- 首屏同步渲染的数据 ----
    bootMs: 0,
    firstRenderMs: 0,
    cacheReady: false,
    recent: [],
    skeletonRows: 3,

    // ---- 启动后异步补充的数据 ----
    cloudReady: false,
    stats: null,

    // 场景卡片
    scenes: [
      {
        key: 'quickread',
        title: 'AI 一页纸快读',
        desc: '论文 / 财报 / 长文 → 一句话结论 + 关键数据 + 风险点 + 原文依据',
        action: '去快读',
        path: '/packages/quickread/pages/index/index'
      },
      {
        key: 'triage',
        title: '日程断舍离',
        desc: '杂乱待办 → 今日必做 Top3 + 可延后 + 建议删除（附理由）+ 时间块',
        action: '去整理',
        path: '/packages/triage/pages/index/index'
      }
    ]
  },

  // ===== 秒开主路径：同步、无网络 =====
  onLoad() {
    const g = app.globalData || {};
    const t0 = Date.now();

    // 直接取 onLaunch 里同步预热的缓存结果，不做任何额外计算。
    const recent = (g.recentTop || []).slice(0, 5);

    this.setData({
      bootMs: g.bootMs || 0,
      cacheReady: !!g.cacheReady,
      recent: recent,
      cloudReady: !!g.cloudReady
    });

    // firstRender 打点：从 app 启动到首屏可见的真实耗时。
    const firstRenderMs = Date.now() - t0;
    this.setData({ firstRenderMs: firstRenderMs });
    app.markBoot('firstRender');
  },

  // ===== 启动之后再异步补数据，此刻首屏已经画完了 =====
  onReady() {
    // 用 setTimeout 0 把同步补数据推迟到首屏渲染之后，避免和首屏抢主线程。
    setTimeout(() => {
      this.refreshStats();
    }, 0);
  },

  onShow() {
    // 从分包页面返回时，缓存可能已被写入新记录，这里同步刷新列表（仍是本地同步读，非网络）。
    const g = app.globalData || {};
    if (g.cache) {
      try {
        this.setData({ recent: g.cache.rank().slice(0, 5) });
      } catch (e) {
        // 读缓存失败保持原样
      }
    }
  },

  // 统计信息：本地计算，不发起网络请求。
  refreshStats() {
    const g = app.globalData || {};
    try {
      if (g.telemetry && typeof g.telemetry.summary === 'function') {
        this.setData({ stats: g.telemetry.summary() });
      }
    } catch (e) {
      // 统计失败不影响页面
    }
  },

  // 跳转场景（分包页面，首次进入由微信按需下载分包；preloadRule 已提前预热 quickread）
  onOpenScene(e) {
    const path = e.currentTarget.dataset.path;
    if (!path) return;
    wx.navigateTo({
      url: path,
      fail() {
        // navigateTo 不能跳 tabBar 页，回退到 switchTab
        wx.switchTab({ url: path });
      }
    });
  },

  // 空态里的行动按钮：直达一页纸快读
  onOpenFirstScene() {
    wx.navigateTo({
      url: '/packages/quickread/pages/index/index',
      fail() {
        wx.switchTab({ url: '/packages/quickread/pages/index/index' });
      }
    });
  },

  // 点击最近记录：跳到详情页并带上记录 id
  onOpenRecent(e) {
    const id = e.currentTarget.dataset.id;
    const scene = e.currentTarget.dataset.scene;
    if (!id) return;
    const url = scene === 'triage'
      ? '/packages/triage/pages/today/index?id=' + id
      : '/packages/quickread/pages/detail/index?id=' + id;
    wx.navigateTo({
      url: url,
      fail() {
        wx.switchTab({ url: '/packages/quickread/pages/index/index' });
      }
    });
  },

  // 清空本地历史（纯本地操作，即时生效）
  onClearRecent() {
    const g = app.globalData || {};
    if (!g.cache) return;
    wx.showModal({
      title: '清空本地记录',
      content: '仅清除本机缓存的最近记录，不影响云端数据。',
      success: (res) => {
        if (!res.confirm) return;
        try {
          g.cache.clear();
        } catch (e) {
          // 忽略
        }
        this.setData({ recent: [] });
        wx.showToast({ title: '已清空', icon: 'success' });
      }
    });
  },

  onShareAppMessage() {
    return {
      title: '秒开 AI：把长文压成一页纸，把待办砍到只剩该做的',
      path: '/pages/home/index'
    };
  }
});
