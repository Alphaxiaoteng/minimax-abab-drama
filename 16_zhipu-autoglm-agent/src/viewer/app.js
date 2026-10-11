"use strict";

/* AutoGLM 端侧执行回放看板 · 单文件回放引擎
 * 数据源：同目录 trace.json（run_demo.py --chaos 自动生成）
 * 离线可用：file:// 下 fetch 被 CORS 拦截时，回退到手动选择 JSON 文件。
 */

const $ = (id) => document.getElementById(id);

const KIND_CN = {
  launch: "启动", tap: "点击", type: "键入", clear: "清空", swipe: "滑动",
  dismiss: "拦截弹窗", type_retry: "输入退避重试",
  watch: "画面看门狗", stall: "画面冻结", plan_drift: "规划漂移纠正",
};

const RECOVERY_KINDS = new Set(["type_retry", "watch", "stall", "plan_drift"]);

const els = {
  screen: $("screen"), elements: $("elements"), popupLayer: $("popup-layer"),
  popupElements: $("popup-elements"), redbox: $("redbox"), redboxLabel: $("redbox-label"),
  screenTag: $("screen-tag"), deviceCaption: $("device-caption"),
  fxLayer: $("fx-layer"), inspectBox: $("inspect-box"), inspectTag: $("inspect-tag"),
  inspTree: $("insp-tree"), inspFields: $("insp-fields"), inspEmpty: $("insp-empty"),
  ifText: $("if-text"), ifRid: $("if-rid"), ifCls: $("if-cls"), ifBounds: $("if-bounds"),
  ifFlags: $("if-flags"), ifConf: $("if-conf"), healChain: $("heal-chain"),
  feed: $("feed"), steps: $("step-list"), healTrack: $("heal-track"),
  healMarks: $("heal-marks"), healPlayhead: $("heal-playhead"), healLog: $("heal-log"),
  deliver: $("deliver-body"), scrub: $("scrub"),
  clock: $("clock"), clockTotal: $("clock-total"),
  stSteps: $("st-steps"), stPopups: $("st-popups"), stRetries: $("st-retries"),
  stHealth: $("st-health"), stElapsed: $("st-elapsed"),
};

const state = {
  data: null, scene: null, events: [], recovery: [],
  duration: 0, cursor: 0, playing: false, speed: 1,
  lastTs: 0, eventIdx: -1, renderedCount: -1,
  lastFxIdx: -1, inspectKey: "", curBase: "", curPopup: "",
  fxTimer: 0, chainTimers: [],
};

/* ---------------- 加载 ---------------- */
function boot(data, srcLabel) {
  state.data = data;
  $("proj-title").textContent = data.project || "AutoGLM";
  $("proj-sub").textContent = data.subtitle || "端侧执行回放看板";
  renderBadges(data);
  $("foot-src").textContent = "数据源 " + (srcLabel || "trace.json");
  $("foot-gen").textContent = data.generated_at ? ("生成于 " + data.generated_at) : "";
  renderTabs(data.scenes || []);
  selectScene(0);
  hideSplash("");
}

function renderBadges(d) {
  const box = $("mode-badges");
  box.innerHTML = "";
  const mode = document.createElement("span");
  mode.className = "badge mode";
  mode.textContent = (d.mode || "normal") === "chaos" ? "故障注入回放" : "标准回放";
  box.appendChild(mode);
  if (d.chaos) {
    const drift = document.createElement("span");
    drift.className = "badge chaos";
    drift.textContent = "UI 漂移 ±" + (d.drift_px || 0) + "px · 输入即清空";
    box.appendChild(drift);
  }
}

function renderTabs(scenes) {
  const nav = $("scene-tabs");
  nav.innerHTML = "";
  scenes.forEach((sc, i) => {
    const t = document.createElement("div");
    t.className = "tab" + (i === 0 ? " active" : "");
    t.dataset.i = String(i);
    const dot = document.createElement("span");
    dot.className = "dot" + (sc.summary && sc.summary.success ? " ok" : "");
    if (sc.summary && sc.summary.success) t.classList.add("done");
    dot.style.background = sc.summary && sc.summary.success ? "var(--green)" : "var(--red)";
    const label = document.createElement("span");
    label.textContent = sc.name || sc.id;
    t.appendChild(dot);
    t.appendChild(label);
    t.addEventListener("click", () => selectScene(i));
    nav.appendChild(t);
  });
}

function selectScene(i) {
  const sc = state.data.scenes[i];
  if (!sc) return;
  state.scene = sc;
  state.events = (sc.events || []).slice().sort((a, b) => (a.t_ms || 0) - (b.t_ms || 0));
  state.recovery = state.events.filter((e) => e.lane === "recovery" || RECOVERY_KINDS.has(e.kind));
  state.duration = state.events.length ? Math.max(1, state.events[state.events.length - 1].t_ms || 1) : 1;
  state.cursor = 0;
  state.eventIdx = -1;
  state.renderedCount = -1;
  state.playing = false;
  $("btn-play").textContent = "▶";
  resetTransientFx();

  document.querySelectorAll(".tab").forEach((t, idx) => t.classList.toggle("active", idx === i));

  // device frame aspect
  const dev = sc.device || {};
  const isDesktop = (dev.width || 0) > (dev.height || 0);
  els.screen.classList.toggle("desktop", isDesktop);
  els.deviceCaption.innerHTML =
    "<b>" + (isDesktop ? "桌面端" : "手机端") + "</b> · 虚拟屏 " +
    (dev.width || "?") + "×" + (dev.height || "?");

  els.scrub.max = String(Math.round(state.duration));
  renderStats(sc);
  renderSteps(sc);
  renderHealStatic();
  paint();            // cursor=0 → shows first event
  requestAnimationFrame(() => setPlay(true));
}

/* ---------------- 静态区块 ---------------- */
function renderStats(sc) {
  const s = sc.summary || {};
  els.stSteps.textContent = (s.ok != null ? s.ok : "?") + " / " + (s.steps != null ? s.steps : "?");
  els.stPopups.textContent = s.popups != null ? s.popups : "0";
  els.stRetries.textContent = s.type_retries != null ? s.type_retries : "0";
  els.stHealth.textContent = s.health != null ? s.health : "0";
  els.stElapsed.textContent = s.elapsed_s != null ? s.elapsed_s.toFixed(2) + "s" : "–";

  // deliverables
  els.deliver.innerHTML = "";
  const dl = document.createElement("dl");
  const hl = sc.highlights || {};
  Object.keys(hl).forEach((k) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = fmtVal(hl[k]);
    dl.appendChild(dt); dl.appendChild(dd);
  });
  if (sc.artifact) {
    const dt = document.createElement("dt"); dt.textContent = "交付件";
    const dd = document.createElement("dd"); dd.className = "art"; dd.textContent = sc.artifact;
    dl.appendChild(dt); dl.appendChild(dd);
  }
  if (dl.children.length) els.deliver.appendChild(dl);
  else els.deliver.innerHTML = '<p style="color:var(--dim);margin:0">本场景无结构化产出</p>';
}

function fmtVal(v) {
  if (v == null) return "–";
  if (typeof v === "number") return (Number.isInteger(v) ? v : v.toFixed(2)).toString();
  if (Array.isArray(v)) return v.map(fmtVal).join(", ");
  if (typeof v === "object") {
    return Object.keys(v).map((k) => k + " " + fmtVal(v[k])).join(" · ");
  }
  return String(v);
}

function renderSteps(sc) {
  els.steps.innerHTML = "";
  const steps = sc.steps || [];
  steps.forEach((st, i) => {
    const li = document.createElement("li");
    li.className = st.status === "ok" ? "ok" : (st.status === "failed" ? "fail" : "");
    li.dataset.i = String(i);
    const sid = document.createElement("span"); sid.className = "sid";
    sid.textContent = st.id || ("step-" + (i + 1));
    const att = document.createElement("span"); att.className = "att";
    att.textContent = (st.attempts && st.attempts > 1 ? "×" + st.attempts + " " : "") +
      (st.error ? "⚠ " + st.error : "");
    li.appendChild(sid); li.appendChild(att);
    els.steps.appendChild(li);
  });
}

/* 自愈时间轴的静态刻度：把 recovery 事件按 t_ms 定位到轨道 */
function renderHealStatic() {
  els.healMarks.innerHTML = "";
  els.healLog.innerHTML = "";
  els.healTrack.classList.toggle("empty", state.recovery.length === 0);
  if (state.recovery.length === 0) {
    const note = document.createElement("li");
    note.style.color = "var(--dim)";
    note.textContent = "本场景未触发自愈事件（脚本一次通过）";
    els.healLog.appendChild(note);
    return;
  }
  state.recovery.forEach((ev, i) => {
    const pos = ((ev.t_ms || 0) / state.duration) * 100;
    const m = document.createElement("div");
    m.className = "heal-mark" + (ev.kind === "type_retry" ? " retry" : " health");
    m.style.left = Math.max(2, Math.min(98, pos)) + "%";
    m.title = (KIND_CN[ev.kind] || ev.kind) + " @" + fmtMs(ev.t_ms);
    m.textContent = ev.kind === "type_retry" ? "↻" : "◈";
    m.addEventListener("click", () => jumpTo(ev.t_ms));
    els.healMarks.appendChild(m);

    const li = document.createElement("li");
    li.className = ev.kind === "type_retry" ? "retry" : "health";
    li.dataset.i = String(i);
    const t = document.createElement("span"); t.className = "t"; t.textContent = fmtMs(ev.t_ms);
    const desc = document.createElement("span");
    desc.textContent = healDesc(ev);
    li.appendChild(t); li.appendChild(desc);
    els.healLog.appendChild(li);
  });
}

function healDesc(ev) {
  const name = KIND_CN[ev.kind] || ev.kind;
  const parts = [name];
  if (ev.spec) parts.push("目标 " + ev.spec);
  if (ev.field) parts.push("字段 " + ev.field);
  if (ev.attempt != null) parts.push("第 " + ev.attempt + " 次退避");
  if (ev.fault) parts.push("故障 " + ev.fault);
  return parts.join(" · ");
}

/* ---------------- 渲染一帧 ---------------- */
/* 屏幕与红框始终以「最近的动作事件」为准；自愈事件（无坐标）只驱动时间轴。 */
function actionEventForCursor() {
  let out = null;
  for (let i = 0; i <= state.eventIdx && i < state.events.length; i++) {
    const e = state.events[i];
    if (e.lane !== "recovery" && !RECOVERY_KINDS.has(e.kind)) out = e;
  }
  return out;
}

function paint() {
  els.clock.textContent = fmtMs(state.cursor);
  els.clockTotal.textContent = fmtMs(state.duration);
  if (document.activeElement !== els.scrub) els.scrub.value = String(Math.round(state.cursor));

  const screenEv = actionEventForCursor();
  if (screenEv) renderScreenFor(screenEv);

  // feed reveal count
  if (state.events.length) {
    let n = 0;
    while (n < state.events.length && (state.events[n].t_ms || 0) <= state.cursor + 1e-6) n++;
    state.eventIdx = n - 1;
    revealFeed(n);
    markSteps(n);
    // 手势动效 + 检查器联动：仅在落到「新事件」时触发一次
    if (state.eventIdx !== state.lastFxIdx) {
      const cur = state.events[state.eventIdx];
      if (cur && cur.lane === "action" && !RECOVERY_KINDS.has(cur.kind)) {
        fireGesture(cur);
        if (cur.key) inspectEl(cur.key, { follow: true });
      }
      state.lastFxIdx = state.eventIdx;
    }
  }
  // heal playhead + log highlight
  els.healPlayhead.style.left = ((state.cursor / state.duration) * 100) + "%";
  const shown = state.recovery.filter((e) => (e.t_ms || 0) <= state.cursor + 1e-6).length;
  els.healLog.querySelectorAll("li").forEach((li, i) => {
    li.classList.toggle("on", i < shown);
    li.classList.toggle("cur", i === shown - 1);
  });
}

function renderScreenFor(ev) {
  const dev = state.scene.device || {};
  const W = dev.width || 1080, H = dev.height || 2400;
  const layout = state.scene.layout || {};
  const baseId = ev.screen;
  const popupId = ev.popup || null;
  state.curBase = baseId || "";
  state.curPopup = popupId || "";

  els.screenTag.textContent = describeScreen(ev);
  els.screenTag.className = "screen-tag" + (ev.kind === "dismiss" ? " popup" : "");

  // base elements
  renderElements(els.elements, layout[baseId], W, H, false);

  // popup overlay snapshot
  if (popupId && layout[popupId]) {
    els.popupLayer.hidden = false;
    renderElements(els.popupElements, layout[popupId], W, H, true);
  } else {
    els.popupLayer.hidden = true;
  }

  // red-box highlight
  if (ev.bounds && ev.bounds.length === 4) {
    const [x1, y1, x2, y2] = ev.bounds;
    els.redbox.hidden = false;
    els.redbox.style.left = pct(x1, W);
    els.redbox.style.top = pct(y1, H);
    els.redbox.style.width = pct(x2 - x1, W);
    els.redbox.style.height = pct(y2 - y1, H);
    els.redbox.classList.toggle("recovery", RECOVERY_KINDS.has(ev.kind));
    els.redboxLabel.textContent = redLabel(ev);
  } else {
    els.redbox.hidden = true;
  }

  renderInspectorTree();
  syncInspectBox();
}

function renderElements(container, def, W, H, inPopup) {
  container.innerHTML = "";
  const list = def && Array.isArray(def.elements) ? def.elements : [];
  const typed = typedValueOnScreen();
  list.forEach((el) => {
    const d = document.createElement("div");
    d.className = "el" + (el.editable ? " input" : "") + (inPopup ? " popup" : "") +
      (el.key === state.inspectKey ? " inspecting" : "");
    d.dataset.key = el.key;
    d.style.left = pct(el.x * W, W);
    d.style.top = pct(el.y * H, H);
    d.style.width = pct(el.w * W, W);
    d.style.height = pct(el.h * H, H);
    d.title = (el.key || "") + (el.text ? " · " + el.text : "");
    let label = el.text || el.key || "";
    if (el.editable && typed && typed.key === el.key && typed.value) {
      label = String(typed.value);
      d.classList.add("filled");
    }
    d.textContent = label;
    container.appendChild(d);
  });
}

function describeScreen(ev) {
  let s = (ev.kind === "dismiss" ? "弹窗 " : "") + (ev.screen || "");
  if (ev.popup) s = ev.screen + "  ⟂  " + ev.popup;
  return s;
}

function redLabel(ev) {
  if (ev.kind === "type_retry") return "自愈 · 输入回读退避重试";
  if (ev.kind === "dismiss") return "看门狗拦截 · " + (ev.text || "弹窗");
  if (ev.kind === "type") return "键入 · " + (ev.text || "");
  if (RECOVERY_KINDS.has(ev.kind)) return "自愈 · " + (KIND_CN[ev.kind] || ev.kind);
  return (KIND_CN[ev.kind] || ev.kind) + " · " + (ev.text || ev.key || "");
}

/* 当前屏最后一个已播 type 事件 → 输入框回填值 */
function typedValueOnScreen() {
  const ev = state.events[state.eventIdx];
  if (!ev) return null;
  let out = null;
  for (let i = 0; i <= state.eventIdx; i++) {
    const e = state.events[i];
    if (e.kind === "type" && e.screen === ev.screen) out = { key: e.key || e.field, value: e.text };
    if (e.kind === "clear" && e.screen === ev.screen) out = null;
  }
  return out;
}

function pct(px, total) { return (Math.max(0, Math.min(100, (px / total) * 100))) + "%"; }
function fmtMs(ms) { return ((ms || 0) / 1000).toFixed(2) + "s"; }
function rnd(a, b) { return Math.round(a + Math.random() * (b - a)); }
function devWH() {
  const d = (state.scene && state.scene.device) || {};
  return [d.width || 1080, d.height || 2400];
}

/* ---------------- 手势动效 Gesture FX ---------------- */
/* 依据 trace 真实坐标渲染点击涟漪 / 滑动方向箭头 / 输入框聚焦动效 */
function fireGesture(ev) {
  clearTimeout(state.fxTimer);
  if (!els.fxLayer) return;
  const [W, H] = devWH();
  els.fxLayer.innerHTML = "";
  if (els.elements.querySelectorAll) {
    els.elements.querySelectorAll(".el.focus").forEach((n) => n.classList.remove("focus"));
  }

  if (ev.kind === "tap" || ev.kind === "dismiss") {
    if (ev.x == null || ev.y == null) return;
    const r = document.createElement("div");
    r.className = "ripple" + (ev.kind === "dismiss" ? " dismiss" : "");
    r.style.left = pct(ev.x, W);
    r.style.top = pct(ev.y, H);
    els.fxLayer.appendChild(r);
  } else if (ev.kind === "type") {
    const node = els.elements.querySelector &&
      els.elements.querySelector('.el[data-key="' + cssEscape(ev.key) + '"]');
    if (node) {
      node.classList.add("focus");
      state.fxTimer = setTimeout(() => node.classList.remove("focus"), 1100);
    }
  } else if (ev.kind === "swipe") {
    drawSwipeArrow(ev, W, H);
  }
}

function cssEscape(s) { return String(s == null ? "" : s).replace(/["\\]/g, "\\$&"); }

function drawSwipeArrow(ev, W, H) {
  const x1 = ev.x1, y1 = ev.y1, x2 = ev.x2, y2 = ev.y2;
  if ([x1, y1, x2, y2].some((v) => v == null)) return;
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const ah = Math.min(30, len * 0.4), aw = 15;
  const bx = x2 - ux * ah, by = y2 - uy * ah;
  const px = -uy, py = ux;
  const svg =
    '<svg class="swipe-arrow fx-fade" width="100%" height="100%" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
    '<line class="trail" x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '"/>' +
    '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + bx + '" y2="' + by + '"/>' +
    '<polygon points="' + x2 + ',' + y2 + ' ' + (bx + px * aw) + ',' + (by + py * aw) + ' ' + (bx - px * aw) + ',' + (by - py * aw) + '"/>' +
    "</svg>";
  els.fxLayer.innerHTML = svg;
}

/* ---------------- 无障碍节点树检查器 ---------------- */
function findLayoutEl(key) {
  const layout = (state.scene && state.scene.layout) || {};
  const order = [state.curBase, state.curPopup].filter(Boolean);
  for (const sid of order) {
    const def = layout[sid];
    if (!def) continue;
    const el = (def.elements || []).find((e) => e.key === key);
    if (el) return { el, sid, popup: !!state.curPopup && sid === state.curPopup };
  }
  return null;
}

/* 优先取真实点击/拦截事件的设备像素 bounds（含抖动），否则回退布局归一化坐标 */
function boundsForEl(key) {
  for (let i = state.events.length - 1; i >= 0; i--) {
    const e = state.events[i];
    if ((e.kind === "tap" || e.kind === "dismiss") && e.key === key && e.bounds) return e.bounds;
  }
  return null;
}

function confForEventKey(key) {
  let out = null;
  for (const e of state.events) {
    if (e.key !== key) continue;
    if (e.kind === "tap" || e.kind === "dismiss" || e.kind === "type") {
      if (e.conf != null) return { conf: e.conf, source: e.source };
      if (!out) out = { conf: null, source: e.source };
    }
  }
  return out;
}

function renderInspectorTree(force) {
  if (!els.inspTree) return;
  const sig = state.curBase + "|" + state.curPopup + "|" + state.inspectKey;
  if (!force && sig === state.inspSig) return;
  state.inspSig = sig;
  els.inspTree.innerHTML = "";
  const layout = (state.scene && state.scene.layout) || {};
  const groups = [];
  if (state.curBase && layout[state.curBase]) groups.push({ sid: state.curBase, popup: false });
  if (state.curPopup && layout[state.curPopup]) groups.push({ sid: state.curPopup, popup: true });
  let count = 0;
  groups.forEach((g) => {
    (layout[g.sid].elements || []).forEach((el) => {
      const node = document.createElement("div");
      node.className = "insp-node" + (g.popup ? " popup" : "") + (el.key === state.inspectKey ? " active" : "");
      node.dataset.key = el.key;
      const nk = document.createElement("span"); nk.className = "nkey"; nk.textContent = el.text || el.key || "(空文本)";
      const nr = document.createElement("span"); nr.className = "nrid"; nr.textContent = el.rid || "—";
      const nt = document.createElement("span"); nt.className = "ntype";
      nt.textContent = el.editable ? "input" : (el.scrollable ? "scroll" : (el.cls || "view"));
      node.appendChild(nk); node.appendChild(nr); node.appendChild(nt);
      const cc = confForEventKey(el.key);
      if (cc && cc.conf != null) {
        const nc = document.createElement("span"); nc.className = "nconf";
        nc.textContent = "◆" + Math.round(cc.conf * 100) + "%";
        node.appendChild(nc);
      }
      node.addEventListener("click", () => inspectEl(el.key));
      els.inspTree.appendChild(node);
      count++;
    });
  });
  if (!count) {
    const e = document.createElement("div");
    e.className = "insp-node"; e.textContent = "当前屏幕无可检查节点";
    els.inspTree.appendChild(e);
  }
}

function inspectEl(key, opts) {
  if (!key) return;
  opts = opts || {};
  state.inspectKey = key;
  renderInspectorTree();
  const found = findLayoutEl(key);
  fillInspectFields(found, key);
  syncInspectBox();
}

function fillInspectFields(found, key) {
  if (!els.inspFields) return;
  const [W, H] = devWH();
  els.inspEmpty.hidden = !!found;
  els.inspFields.hidden = !found;
  if (!found) {
    els.ifText.textContent = "控件不在当前屏幕";
    els.ifRid.textContent = "—"; els.ifCls.textContent = "—";
    els.ifBounds.textContent = "—"; els.ifFlags.textContent = "—";
    els.ifConf.textContent = "—";
    return;
  }
  const el = found.el;
  const b = boundsForEl(key);
  let x1, y1, x2, y2;
  if (b) { [x1, y1, x2, y2] = b; }
  else { x1 = Math.round(el.x * W); y1 = Math.round(el.y * H); x2 = x1 + Math.round(el.w * W); y2 = y1 + Math.round(el.h * H); }
  els.ifText.textContent = el.text || (el.desc ? el.desc + " (描述)" : "(无文本)");
  els.ifRid.textContent = el.rid || "(无 resource-id)";
  els.ifCls.textContent = (el.cls || "—") + (found.popup ? " · 弹窗层" : "");
  els.ifBounds.textContent = "[" + x1 + ", " + y1 + ", " + x2 + ", " + y2 + "]  " + (x2 - x1) + "×" + (y2 - y1);
  const flags = [];
  if (el.clickable) flags.push("可点击");
  if (el.editable) flags.push("可编辑");
  if (el.scrollable) flags.push("可滚动");
  if (el.noisy) flags.push("OCR 噪声");
  if (el.desc) flags.push("desc");
  els.ifFlags.textContent = flags.join(" · ") || "—";
  const cc = confForEventKey(key);
  els.ifConf.textContent = "";
  if (cc && cc.conf != null) {
    const bar = document.createElement("span"); bar.className = "conf-bar";
    bar.style.width = Math.round(cc.conf * 70) + "px";
    els.ifConf.appendChild(bar);
    els.ifConf.appendChild(document.createTextNode(" " + Math.round(cc.conf * 100) + "% · 通道 " + (cc.source || "?")));
  } else if (cc) {
    els.ifConf.textContent = "输入类动作 · 依赖回读校验（无定位置信）";
  } else {
    els.ifConf.textContent = "未被 Agent 触达 · 无识别记录";
  }
}

function syncInspectBox() {
  if (!els.inspectBox) return;
  const found = state.inspectKey ? findLayoutEl(state.inspectKey) : null;
  if (!found) { els.inspectBox.hidden = true; return; }
  const [W, H] = devWH();
  const el = found.el;
  const b = boundsForEl(state.inspectKey);
  let x1, y1, x2, y2;
  if (b) { [x1, y1, x2, y2] = b; }
  else { x1 = el.x * W; y1 = el.y * H; x2 = x1 + el.w * W; y2 = y1 + el.h * H; }
  els.inspectBox.hidden = false;
  els.inspectBox.style.left = pct(x1, W);
  els.inspectBox.style.top = pct(y1, H);
  els.inspectBox.style.width = pct(x2 - x1, W);
  els.inspectBox.style.height = pct(y2 - y1, H);
  els.inspectTag.textContent = (el.rid ? el.rid + " · " : el.key) + (b ? " (实测)" : "");
}

/* ---------------- 一键混沌演练场 Live Chaos Playground ---------------- */
const HEAL_CHAINS = {
  jitter: {
    steps: [
      ["感知层：注入 UI 元素坐标漂移 ±30px", ""],
      ["看门狗体检：画面非黑屏 / 非冻结 → 放行定位", ""],
      ["多通道重定位：resource-id → text → 视觉模板 依次降级", ""],
      ["漂移容忍：中心位移 ≤ 阈值，二次确认接受新位置", ""],
      ["视觉自校验通过 · 目标锁定", "ok"],
    ],
    run: jitterOverlay,
  },
  ad: {
    steps: [
      ["弹窗治理器：突发营销弹窗阻断主流程", ""],
      ["扫描关闭策略：跳过 / × / 以后再说 命中", ""],
      ["定位关闭控件坐标 · 发起拦截点击", ""],
      ["弹窗关闭 · 主界面恢复", "ok"],
    ],
    run: adOverlay,
  },
  net: {
    steps: [
      ["键入后回读输入框：内容为空（网络抖动吞输入）", ""],
      ["判定静默失败 → 触发输入退避重试", ""],
      ["指数退避 0.6s 等待链路恢复", ""],
      ["重定位输入框并重新键入", ""],
      ["二次回读校验通过 · 输入确认", "ok"],
    ],
    run: netOverlay,
  },
};

function revealChain(steps) {
  if (!els.healChain) return;
  state.chainTimers.forEach(clearTimeout); state.chainTimers = [];
  els.healChain.innerHTML = "";
  const lis = steps.map((s, i) => {
    const li = document.createElement("li");
    const num = document.createElement("span"); num.className = "cnum"; num.textContent = String(i + 1);
    const txt = document.createElement("span"); txt.textContent = s[0];
    li.appendChild(num); li.appendChild(txt);
    li._kind = s[1];
    els.healChain.appendChild(li);
    return li;
  });
  lis.forEach((li, i) => {
    const t = setTimeout(() => li.classList.add(li._kind === "ok" ? "ok" : "on"), 380 * (i + 1));
    state.chainTimers.push(t);
  });
}

function jitterOverlay() {
  const nodes = els.elements.querySelectorAll ? Array.prototype.slice.call(els.elements.querySelectorAll(".el")) : [];
  nodes.forEach((n) => {
    n.style.transition = "transform .18s ease";
    n.style.transform = "translate(" + rnd(-30, 30) + "px," + rnd(-30, 30) + "px)";
  });
  const t = setTimeout(() => {
    nodes.forEach((n) => { n.style.transform = ""; });
    state.chainTimers.push(setTimeout(() => nodes.forEach((n) => { n.style.transition = ""; }), 260));
  }, 520);
  state.chainTimers.push(t);
}

function adOverlay() {
  if (!els.screen) return;
  const box = document.createElement("div");
  box.className = "chaos-ad";
  box.innerHTML = '<div class="ad-dim"></div>' +
    '<div class="ad-box"><span class="ad-skip">跳过 ✕</span>' +
    '<div class="ad-title">限时大促 · 全场五折</div>' +
    '<div class="ad-body">推广位演示：营销弹窗突发阻断，观察弹窗治理器拦截</div></div>';
  els.screen.appendChild(box);
  state.adEl = box;
  box.addEventListener("click", closeAd);
  state.chainTimers.push(setTimeout(closeAd, 3400));
}

function closeAd() {
  const box = state.adEl; state.adEl = null;
  if (!box || !box.remove) return;
  box.classList.add("closing");
  setTimeout(() => box.remove(), 520);
}

function netOverlay() {
  const inp = els.elements.querySelector ? els.elements.querySelector(".el.input") : null;
  if (!inp) return;
  inp.classList.add("net-bad");
  state.chainTimers.push(setTimeout(() => {
    inp.classList.remove("net-bad"); inp.classList.add("net-ok");
    state.chainTimers.push(setTimeout(() => inp.classList.remove("net-ok"), 2200));
  }, 900));
}

function clearChaos() {
  state.chainTimers.forEach(clearTimeout); state.chainTimers = [];
  if (state.adEl && state.adEl.remove) { state.adEl.remove(); state.adEl = null; }
  if (els.elements.querySelectorAll) {
    els.elements.querySelectorAll(".el").forEach((n) => {
      n.style.transform = ""; n.style.transition = "";
      n.classList.remove("net-bad", "net-ok");
    });
  }
  if (!els.healChain) return;
  els.healChain.innerHTML = "";
  const ph = document.createElement("li");
  ph.className = "chain-empty";
  ph.textContent = "点击上方向注入按钮 · 实时演示端侧 Agent 自愈决策链";
  els.healChain.appendChild(ph);
}

function runChaos(fx) {
  if (!state.scene) return;
  setPlay(false);
  clearChaos();
  const chain = HEAL_CHAINS[fx];
  if (!chain) return;
  if (chain.run) chain.run();
  revealChain(chain.steps);
}

function resetTransientFx() {
  clearTimeout(state.fxTimer);
  if (els.fxLayer) els.fxLayer.innerHTML = "";
  if (els.inspectBox) els.inspectBox.hidden = true;
  state.inspectKey = ""; state.lastFxIdx = -1; state.inspSig = "";
  clearChaos();
}

/* ---------------- Feed ---------------- */
function revealFeed(n) {
  if (n === state.renderedCount) return;
  if (n > state.renderedCount) {
    for (let i = Math.max(0, state.renderedCount + 1); i < n; i++) els.feed.appendChild(feedRow(state.events[i]));
  } else {
    els.feed.innerHTML = "";
    for (let i = 0; i < n; i++) els.feed.appendChild(feedRow(state.events[i]));
  }
  state.renderedCount = n;
  els.feed.scrollTop = els.feed.scrollHeight;
}

function feedRow(ev) {
  const li = document.createElement("li");
  const isReco = ev.lane === "recovery" || RECOVERY_KINDS.has(ev.kind);
  li.className = "ev" + (isReco ? " reco" : "");
  const k = document.createElement("span");
  k.className = "k " + (ev.kind === "type_retry" ? "type_retry" : (ev.kind === "dismiss" ? "dismiss" : ev.kind));
  k.textContent = KIND_CN[ev.kind] || ev.kind;
  const d = document.createElement("span"); d.className = "desc";
  d.innerHTML = feedDesc(ev, isReco);
  const r = document.createElement("span"); r.className = "reco"; r.textContent = fmtMs(ev.t_ms);
  li.appendChild(k); li.appendChild(d); li.appendChild(r);
  return li;
}

function feedDesc(ev, isReco) {
  const bits = [];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  if (ev.kind === "launch") bits.push("启动 " + (ev.target || "?"));
  else if (ev.kind === "type") bits.push('“' + esc(ev.text || "") + '”');
  else if (ev.kind === "clear") bits.push("清空 " + (ev.field || ""));
  else if (ev.kind === "dismiss") bits.push("拦截 “" + esc(ev.text || "") + "”");
  else if (ev.kind === "type_retry") bits.push("回读退避 " + (ev.attempt != null ? "×" + ev.attempt : "") + (ev.fault ? " " + esc(ev.fault) : ""));
  else bits.push(esc(ev.text || ev.key || ev.screen || ""));
  const scr = '<span class="q">' + esc(isReco && ev.screen ? ev.screen : (ev.screen || "")) + "</span>";
  return bits.join(" ") + " " + scr;
}

/* ---------------- Steps 同步 ---------------- */
function markSteps(n) {
  const items = els.steps.querySelectorAll("li");
  const total = state.events.length;
  items.forEach((li, i) => {
    // 事件推进比例映射到步骤进度条视觉高亮（末步在轨迹末尾达成）
    const reach = total ? (n / total) : 0;
    const threshold = (i + 1) / (items.length || 1);
    li.classList.toggle("hit", reach >= threshold - 1e-6);
  });
}

/* ---------------- 播放控制 ---------------- */
function setPlay(on) {
  if (!state.events.length) return;
  state.playing = on;
  $("btn-play").textContent = on ? "❚❚" : "▶";
  if (on) {
    if (state.cursor >= state.duration) state.cursor = 0;
    state.lastTs = performance.now();
    requestAnimationFrame(loop);
  }
}

function loop(ts) {
  if (!state.playing) return;
  const dt = ts - state.lastTs;
  state.lastTs = ts;
  state.cursor = Math.min(state.duration, state.cursor + dt * state.speed);
  advanceCursorEvents();
  paint();
  if (state.cursor >= state.duration) { setPlay(false); return; }
  requestAnimationFrame(loop);
}

function advanceCursorEvents() {
  let n = 0;
  while (n < state.events.length && (state.events[n].t_ms || 0) <= state.cursor + 1e-6) n++;
  state.eventIdx = n - 1;
}

function jumpTo(ms) {
  setPlay(false);
  state.cursor = Math.max(0, Math.min(state.duration, ms));
  advanceCursorEvents();
  paint();
}

/* 事件间跳跃（对齐真实操作时刻，不插值） */
function jumpEvent(delta) {
  setPlay(false);
  let idx = state.eventIdx;
  if (delta > 0) idx = Math.min(state.events.length - 1, idx + 1);
  else idx = Math.max(0, idx - 1);
  if (state.events[idx]) {
    state.cursor = state.events[idx].t_ms || 0;
    state.eventIdx = idx;
    paint();
  }
}

function wireControls() {
  $("btn-play").addEventListener("click", () => setPlay(!state.playing));
  $("btn-next").addEventListener("click", () => jumpEvent(1));
  $("btn-prev").addEventListener("click", () => jumpEvent(-1));
  $("btn-reset").addEventListener("click", () => jumpTo(0));
  $("speed").addEventListener("change", (e) => { state.speed = parseFloat(e.target.value) || 1; });
  els.scrub.addEventListener("input", (e) => jumpTo(parseFloat(e.target.value) || 0));
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); setPlay(!state.playing); }
    else if (e.code === "ArrowRight") jumpEvent(1);
    else if (e.code === "ArrowLeft") jumpEvent(-1);
  });
  $("trace-file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try { boot(JSON.parse(reader.result), f.name); }
      catch (err) { hideSplash("解析失败：" + err.message); }
    };
    reader.readAsText(f);
  });

  // 无障碍检查器：点击仿真屏幕上的控件节点 → 联动高亮
  if (els.screen && els.screen.addEventListener) {
    els.screen.addEventListener("click", (e) => {
      const t = e.target && e.target.closest ? e.target.closest(".el") : null;
      if (t && t.dataset && t.dataset.key) inspectEl(t.dataset.key);
    });
  }

  // 一键混沌演练场
  if (document.querySelectorAll) {
    document.querySelectorAll(".chaos-btn").forEach((b) => {
      b.addEventListener("click", () => {
        const fx = b.dataset ? b.dataset.fx : "";
        if (fx === "reset") { setPlay(false); clearChaos(); return; }
        runChaos(fx);
      });
    });
  }
  clearChaos();
}

/* ---------------- Splash ---------------- */
function showSplash(msg) { $("splash").classList.remove("hidden"); if (msg) $("splash-msg").textContent = msg; }
function hideSplash(errMsg) {
  const sp = $("splash");
  if (!errMsg) { sp.classList.add("hidden"); return; }
  $("splash-msg").textContent = errMsg;
  $("splash-hint").hidden = false;
  sp.classList.remove("hidden");
}

/* ---------------- 入口 ---------------- */
async function autoLoad() {
  wireControls();
  showSplash("读取 trace.json …");
  try {
    const resp = await fetch("trace.json", { cache: "no-store" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    boot(data, "trace.json");
  } catch (err) {
    hideSplash("自动读取失败：" + err.message);
    $("splash-hint").hidden = false;
    $("splash-hint").innerHTML =
      "浏览器以 <code>file://</code> 直开会拦截本地 JSON。请点右上「载入 trace.json」手动选择，" +
      "或在项目根运行 <code>uv run python -m http.server --directory src/viewer 8080</code> " +
      "后访问 <code>http://127.0.0.1:8080/</code>。";
  }
}

if (typeof document !== "undefined" && document.getElementById("scene-tabs")) {
  autoLoad();
}
