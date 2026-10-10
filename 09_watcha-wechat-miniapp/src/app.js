// 应用入口。启动路径上只做三件事，全部同步完成，保证「秒开」：
//  1) 记 t0 打点（telemetry）——用于首页如实展示首屏耗时；
//  2) 初始化云开发（只在配置了 CLOUD_ENV 时执行，失败也不阻塞）；
//  3) 同步预热最近记录缓存（createWxStorage + createCache），把数据挂到 globalData，
//     首页 onLoad 直接读 globalData 渲染，不 await 任何网络请求。
// 关键决策：这里绝不 await AI 调用。AI 结果由页面在 onReady 之后异步刷新，首屏永远先出内容。

const config = require('./config.js');
const { createCache, createWxStorage } = require('./utils/cache.js');
const { createTelemetry } = require('./analytics/telemetry.js');

const CACHE_NAMESPACE = 'wa_recent';
const CACHE_LIMIT = 30;

App({
  globalData: {
    // 首屏渲染需要的数据，onLaunch 同步填好
    bootMs: 0,
    recentTop: [],
    cacheReady: false,
    telemetry: null,
    cache: null,
    cloudReady: false,
    // 跨页面复用的最后一次分析结果（详情页/分享卡片读取）
    lastResult: null
  },

  onLaunch() {
    const t0 = Date.now();

    // ---- 1) 打点：先记 t0，后面的 firstRender 由首页写回 ----
    let telemetry = null;
    try {
      telemetry = createTelemetry({ storage: createWxStorage() });
      telemetry.mark('appLaunch', t0);
      this.globalData.telemetry = telemetry;
    } catch (e) {
      // 打点失败绝不影响启动
    }

    // ---- 2) 云开发初始化：无环境配置时直接跳过，走离线降级 ----
    this.initCloudSafe();

    // ---- 3) 同步预热缓存：这是秒开的关键路径，全部同步 API ----
    try {
      const cache = createCache({ storage: createWxStorage(), namespace: CACHE_NAMESPACE, limit: CACHE_LIMIT });
      this.globalData.cache = cache;
      // rank() 是同步的：按 score 降序、ts 降序，取 Top 8 供首页直接渲染
      this.globalData.recentTop = cache.rank().slice(0, 8);
      this.globalData.cacheReady = true;
    } catch (e) {
      // 存储不可用（如首次安装、隐私受限）时保持空数组，首页显示空态，不阻塞
      this.globalData.recentTop = [];
      this.globalData.cacheReady = false;
    }

    this.globalData.bootMs = Date.now() - t0;
  },

  // 云开发初始化：只在有 env 时才调用 wx.cloud.init，任何异常都吞掉并标记不可用。
  initCloudSafe() {
    if (!config.CLOUD_ENV) {
      this.globalData.cloudReady = false;
      return;
    }
    try {
      if (typeof wx === 'undefined' || !wx.cloud || typeof wx.cloud.init !== 'function') {
        this.globalData.cloudReady = false;
        return;
      }
      wx.cloud.init({ env: config.CLOUD_ENV, traceUser: true });
      this.globalData.cloudReady = true;
    } catch (e) {
      this.globalData.cloudReady = false;
    }
  },

  // 供页面回写打点（首页首屏渲染完成时调用）
  markBoot(name) {
    const telemetry = this.globalData.telemetry;
    if (!telemetry) return;
    try { telemetry.mark(name, Date.now()); } catch (e) {}
  },

  // 供页面记录一次运行：scene / ms / mode / ok
  recordRun(run) {
    const telemetry = this.globalData.telemetry;
    if (!telemetry) return;
    try { telemetry.recordRun(run); } catch (e) {}
  }
});
