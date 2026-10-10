// 最近记录缓存。核心卖点「秒开」依赖它：app 启动同步 load + rank，直接 setData，零网络阻塞。
// storage 抽象出 getSync/setSync/removeSync，方便 wx 实现与 Node 测试的内存实现共用同一套逻辑。

function createCache({ storage, namespace, limit } = {}) {
  if (!storage || typeof storage.getSync !== 'function' || typeof storage.setSync !== 'function') {
    throw new Error('cache: storage 必须实现 getSync/setSync');
  }
  const ns = namespace || 'wa_cache';
  const cap = limit && limit > 0 ? limit : 30;
  const key = ns + '__items';

  function persist(items) {
    storage.setSync(key, { items, updatedAt: Date.now() });
  }

  function load() {
    const raw = storage.getSync(key);
    if (raw && Array.isArray(raw.items)) return { items: raw.items.slice(0, cap) };
    return { items: [] };
  }

  function normalizeRecord(record) {
    const r = record || {};
    return {
      id: r.id || ('rec_' + Date.now() + '_' + hash(r)),
      scene: r.scene || 'quickread',
      title: r.title || '未命名',
      summary: r.summary || '',
      raw: r.raw || '',
      ts: typeof r.ts === 'number' ? r.ts : Date.now(),
      hit: typeof r.hit === 'number' ? r.hit : 0,
      score: typeof r.score === 'number' ? r.score : 0,
      tags: Array.isArray(r.tags) ? r.tags : [],
      meta: r.meta || {}
    };
  }

  function hash(r) {
    let h = 0;
    const s = String(r.raw || r.title || '');
    for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
    return h.toString(16);
  }

  function put(record) {
    const norm = normalizeRecord(record);
    const current = load().items;
    const idx = current.findIndex(function (it) { return it.id === norm.id; });
    if (idx !== -1) { current[idx] = norm; } else { current.unshift(norm); }
    if (current.length > cap) current.length = cap;
    persist(current);
    return norm;
  }

  function list() { return load().items; }

  function get(id) {
    const found = load().items.find(function (it) { return it.id === id; });
    return found || null;
  }

  // 按 score 降序、ts 降序排列，用于首页 Top N 秒开。
  function rank() {
    return load().items.slice().sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return b.ts - a.ts;
    });
  }

  function search(keyword) {
    if (!keyword) return load().items;
    const kw = String(keyword).toLowerCase();
    return load().items.filter(function (it) {
      return (it.title + it.summary + it.raw).toLowerCase().indexOf(kw) !== -1;
    });
  }

  function remove(id) {
    const current = load().items;
    const next = current.filter(function (it) { return it.id !== id; });
    if (next.length !== current.length) { persist(next); return true; }
    return false;
  }

  function stats() {
    const items = load().items;
    let bytes = 0;
    let lastAt = 0;
    for (const it of items) {
      bytes += JSON.stringify(it).length;
      if (it.ts > lastAt) lastAt = it.ts;
    }
    return { count: items.length, hitEstimate: items.length, bytes: bytes, lastAt: lastAt };
  }

  function clear() {
    storage.removeSync(key);
  }

  return { load, put, list, get, rank, search, remove, stats, clear };
}

function createWxStorage() {
  return {
    getSync: function (k) { try { return wx.getStorageSync(k) || null; } catch (e) { return null; } },
    setSync: function (k, v) { try { wx.setStorageSync(k, v); } catch (e) {} },
    removeSync: function (k) { try { wx.removeStorageSync(k); } catch (e) {} }
  };
}

module.exports = { createCache, createWxStorage };