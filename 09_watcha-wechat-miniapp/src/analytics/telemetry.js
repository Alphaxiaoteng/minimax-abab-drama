// 轻量埋点：秒开打点 + 运行统计。持久化到 storage，重启可回看；全程 try/catch，绝不影响主流程。
// mark 记录阶段时间戳（appLaunch/firstRender/homeCache 等），bootReport 汇总首屏耗时，recordRun 记每次 AI/本地结果。

function createTelemetry({ storage } = {}) {
  const store = storage || memoryStorage();
  const BOOT_KEY = 'wa_telemetry_boot';
  const RUN_KEY = 'wa_telemetry_runs';

  function readJSON(key, fallback) {
    try {
      const raw = store.getSync(key);
      if (raw && typeof raw === 'object') return raw;
      if (typeof raw === 'string' && raw) return JSON.parse(raw);
    } catch (e) {}
    return fallback;
  }
  function writeJSON(key, value) {
    try { store.setSync(key, value); } catch (e) {}
  }

  function marks() { return readJSON(BOOT_KEY, {}); }

  function mark(name, at) {
    if (!name) return;
    const m = marks();
    m[name] = typeof at === 'number' ? at : Date.now();
    writeJSON(BOOT_KEY, m);
  }

  function bootReport() {
    const m = marks();
    const start = m.appLaunch;
    const out = { marks: m, firstRenderMs: 0, homeCacheMs: 0 };
    if (typeof start === 'number') {
      if (typeof m.firstRender === 'number') out.firstRenderMs = m.firstRender - start;
      if (typeof m.homeCache === 'number') out.homeCacheMs = m.homeCache - start;
    }
    return out;
  }

  function recordRun(run) {
    const r = run || {};
    const list = readJSON(RUN_KEY, []);
    const arr = Array.isArray(list) ? list : [];
    arr.push({ scene: r.scene || '', ms: typeof r.ms === 'number' ? r.ms : 0, mode: r.mode || 'local', ok: r.ok !== false, at: Date.now() });
    if (arr.length > 100) arr.splice(0, arr.length - 100);
    writeJSON(RUN_KEY, arr);
  }

  function summary() {
    const arr = readJSON(RUN_KEY, []);
    const list = Array.isArray(arr) ? arr : [];
    const total = list.length;
    let okCount = 0, cloudCount = 0, localCount = 0, sumMs = 0;
    for (const it of list) {
      if (it.ok) okCount += 1;
      if (it.mode === 'local') localCount += 1; else cloudCount += 1;
      sumMs += it.ms || 0;
    }
    return {
      total: total,
      okRate: total ? Math.round((okCount / total) * 100) : 0,
      cloudCount: cloudCount,
      localCount: localCount,
      avgMs: total ? Math.round(sumMs / total) : 0,
      boot: bootReport()
    };
  }

  function clear() {
    try { store.removeSync(BOOT_KEY); store.removeSync(RUN_KEY); } catch (e) {}
  }

  return { mark, bootReport, recordRun, summary, clear };
}

// Node 测试用的内存 storage，无需 wx。
function memoryStorage() {
  const map = Object.create(null);
  return {
    getSync: function (k) { return map[k]; },
    setSync: function (k, v) { map[k] = v; },
    removeSync: function (k) { delete map[k]; }
  };
}

module.exports = { createTelemetry, memoryStorage };