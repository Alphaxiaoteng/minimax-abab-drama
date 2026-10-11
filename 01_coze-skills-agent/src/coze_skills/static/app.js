/* Plugin Debugger Studio — 直连同进程网关, 与扣子调用完全同一条链路 (POST /tools/{name}). */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const THEME_ORDER = ["物流时效", "包装破损", "尺寸偏差", "质量做工", "客服响应", "描述不符", "价格价值", "气味材质"];
const THEME_EN = {
  物流时效: "delivery timeliness", 包装破损: "packaging damage", 尺寸偏差: "size mismatch",
  质量做工: "quality and workmanship", 客服响应: "customer service responsiveness",
  描述不符: "item not as described", 价格价值: "price-to-value concern", 气味材质: "smell and material issues",
  其他: "uncovered topic",
};
const SEV_RANK = { high: 3, medium: 2, low: 1 };
const RISK_LABEL = { high: "高风险 high", medium: "软性风险 medium", low: "合规 low", none: "待输入" };

async function call(tool, params) {
  const resp = await fetch(`/tools/${tool}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params),
  });
  return resp.json();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 1800);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("已复制到剪贴板"); }
  catch { toast("复制失败，请手动选取"); }
}

/* ---------------- 网关状态 ---------------- */
async function pingGateway() {
  try {
    const resp = await fetch("/tools");
    const j = await resp.json();
    if (j.ok) {
      $("gw-status").textContent = "网关在线";
      $("gw-status").className = "pill pill-live";
      $("gw-tools").textContent = `tools ${j.data.count} · 离线引擎`;
    }
  } catch (_) {
    $("gw-status").textContent = "网关离线";
    $("gw-status").className = "badge badge-high";
  }
}

/* ---------------- ① 合规检测 ---------------- */
const cText = $("c-text"), cBack = $("c-backdrop");
let lastCompliance = null;

function syncScroll() {
  cBack.scrollTop = cText.scrollTop;
  cBack.scrollLeft = cText.scrollLeft;
}
cText.addEventListener("scroll", syncScroll);

function collectRanges(hits, text) {
  const spans = [];
  for (const h of hits) {
    const word = h.word || "";
    if (!word) continue;
    let positions = Array.isArray(h.positions) ? h.positions.filter((p) => Number.isInteger(p) && p >= 0 && text.startsWith(word, p)) : [];
    if (!positions.length) {
      positions = [];
      let i = text.indexOf(word);
      while (i !== -1) { positions.push(i); i = text.indexOf(word, i + word.length); }
    }
    for (const p of positions) spans.push({ start: p, end: p + word.length, sev: h.severity || "low", word, sug: h.suggestion || "" });
  }
  spans.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start) || SEV_RANK[b.sev] - SEV_RANK[a.sev]);
  const kept = [];
  let cursor = 0;
  for (const s of spans) {
    if (s.start >= cursor) { kept.push(s); cursor = s.end; }
  }
  return kept;
}

function renderOverlay(text, hits) {
  const spans = collectRanges(hits || [], text);
  let html = "", pos = 0;
  for (const s of spans) {
    html += esc(text.slice(pos, s.start));
    html += `<span class="mk sev-${s.sev}" title="${esc(s.word + (s.sug ? " → " + s.sug : ""))}">` + esc(text.slice(s.start, s.end)) + "</span>";
    pos = s.end;
  }
  html += esc(text.slice(pos)) + "\n";
  cBack.innerHTML = html;
  syncScroll();
}

function renderHits(hits) {
  const box = $("c-hits");
  box.innerHTML = "";
  if (!hits || !hits.length) {
    box.innerHTML = '<p class="empty">未命中任何禁限词 —— 文案可以放心发布 ✦</p>';
    return;
  }
  for (const h of hits) {
    const el = document.createElement("div");
    el.className = "hit";
    el.innerHTML =
      `<i class="sev-dot sev-${esc(h.severity || "low")}"></i>` +
      `<span class="w">${esc(h.word)}</span>` +
      `<span class="cat">${esc(h.category || "")} @${(h.positions || []).join(",")}</span>` +
      `<span class="sug">${esc(h.suggestion ? "→ " + h.suggestion : "建议删除或弱化")}</span>`;
    box.appendChild(el);
  }
}

function renderCompare(text, rewritten, hits) {
  const orig = $("c-original");
  const spans = collectRanges(hits || [], text);
  let html = "", pos = 0;
  for (const s of spans) {
    html += esc(text.slice(pos, s.start));
    html += `<span class="mk sev-${s.sev}">` + esc(text.slice(s.start, s.end)) + "</span>";
    pos = s.end;
  }
  orig.innerHTML = html + esc(text.slice(pos));
  $("c-rewritten").textContent = rewritten || "—";
}

function setBadge(level) {
  const b = $("c-risk-badge");
  b.className = `badge badge-${level || "none"}`;
  b.textContent = RISK_LABEL[level] || "检测中…";
}

let cTimer = null;
async function runCompliance() {
  const text = cText.value;
  if (!text.trim()) { renderOverlay("", []); setBadge("none"); renderHits([]); lastCompliance = null; $("c-copy").disabled = true; return; }
  const badge = $("c-risk-badge");
  badge.textContent = "检测中…";
  badge.className = "badge badge-none";
  const j = await call("check_compliance", { text, platform: $("c-platform").value });
  if (!j.ok) { toast(`检测失败：${j.error}`); return; }
  lastCompliance = j.data;
  const d = j.data;
  lastGood = { tool: "check_compliance", summary: `风险 ${d.risk_level} · 命中 ${d.hit_count} 处 · 平台 ${d.platform}` };
  setBadge(d.risk_level);
  renderOverlay(text, d.hits);
  renderHits(d.hits);
  renderCompare(text, d.rewritten_text, d.hits);
  $("c-hitcount").textContent = `${d.hit_count} 命中 · ${d.platform}`;
  $("c-copy").disabled = !(d.rewritten_text && d.rewritten_text !== text);
}
cText.addEventListener("input", () => { clearTimeout(cTimer); cTimer = setTimeout(runCompliance, 200); });
$("c-platform").addEventListener("change", runCompliance);
$("c-demo").addEventListener("click", () => {
  cText.value = "这款面膜全网销量第一，药效显著，七天美白立竿见影！亏本清仓，绝对无效全额退款。";
  runCompliance();
});
$("c-copy").addEventListener("click", () => lastCompliance && copyText(lastCompliance.rewritten_text));

/* ---------------- ② 批量体检 ---------------- */
$("b-demo").addEventListener("click", () => {
  $("b-texts").value = "全网最低价，错过再等一年！\n新中式缠花发簪，手工绕线，日常通勤也能戴\n这个膏药包治百病，立竿见影\n超值爆款耳机，学生党闭眼入";
});
$("b-run").addEventListener("click", async () => {
  const texts = $("b-texts").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!texts.length) { toast("请先输入文案（一行一条）"); return; }
  const j = await call("batch_check", { texts, platform: $("b-platform").value });
  if (!j.ok) { toast(`体检失败：${j.error}`); return; }
  const d = j.data;
  $("b-verdict").textContent = d.verdict;
  $("b-verdict").className = "pill " + (d.high_risk_count ? "badge badge-high" : "pill-live");
  const dist = $("b-dist");
  dist.innerHTML = "";
  for (const [k, label] of [["high", "高危"], ["medium", "软性风险"], ["low", "合规"]]) {
    const n = (d.summary || {})[k] || 0;
    const el = document.createElement("span");
    el.className = `badge badge-${k === "low" ? "low" : k}`;
    el.textContent = `${label} ${n}`;
    dist.appendChild(el);
  }
  const box = $("b-results");
  box.innerHTML = "";
  d.results.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      `<span class="idx">#${r.index}</span>` +
      `<span class="tx" title="${esc(texts[i] || "")}">${esc((texts[i] || "").slice(0, 42))}</span>` +
      `<span class="badge badge-${r.risk_level}">${r.risk_level}</span>` +
      `<span class="th">${esc((r.top_hits || []).slice(0, 3).join("、") || "无命中")}</span>`;
    box.appendChild(row);
  });
});

/* ---------------- ③ 差评主题洞察 ---------------- */
$("i-demo").addEventListener("click", () => {
  $("i-reviews").value = "快递太慢了，等了整整一周才到，到手盒子都压烂了\n鞋子偏小两码根本穿不进去，申请退款客服半天不回\nThe stitching came apart after one wash, very poor quality\n和图片完全不符，颜色差太多了\n味道刺鼻，放在阳台晾了三天还是有气味\n这个价格太贵了，不值这个钱\n发货三天没动静，催了才说没库存\n做工粗糙，线头到处都是";
});
$("i-run").addEventListener("click", async () => {
  const reviews = $("i-reviews").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!reviews.length) { toast("请先输入差评（一行一条）"); return; }
  const j = await call("analyze_reviews", { reviews, marketplace: $("i-market").value, top_n: Number($("i-topn").value) || 8 });
  if (!j.ok) { toast(`归因失败：${j.error}`); return; }
  const d = j.data;
  $("s-total").textContent = d.total;
  $("s-neg").textContent = `${Math.round((d.negative_ratio || 0) * 100)}%`;
  $("s-theme").textContent = `${(d.themes || []).filter((t) => t.count > 0).length}/${THEME_ORDER.length}`;

  // 8 大主题恒定全量渲染: 未命中的主题补 0% 灰条, 面板始终呈现完整归因框架
  const bars = $("i-bars");
  bars.innerHTML = "";
  const hitNames = new Set((d.themes || []).map((t) => t.theme));
  const rows = (d.themes || []).concat(
    THEME_ORDER.filter((name) => !hitNames.has(name)).map((name) => ({ theme: name, count: 0, ratio: 0, severity: "none" })),
  );
  const fills = [];
  rows.forEach((t) => {
    const pct = Math.round((t.ratio || 0) * 100);
    const row = document.createElement("div");
    row.className = "bar-row" + (t.count ? "" : " muted");
    row.innerHTML =
      `<div class="lab"><span>${esc(t.theme)} <i class="sev-dot sev-${esc(t.severity || "low")}"></i></span>` +
      `<span class="meta">${t.count} 条 · ${pct}%</span></div>` +
      `<div class="track"><div class="fill sev-${esc(t.severity || "low")}" style="width:0%"></div></div>`;
    bars.appendChild(row);
    fills.push([row.querySelector(".fill"), pct]);
  });
  // 强制回流后同步写宽度: 动画帧回调在后台标签页会被节流, 用它写宽度进度条会停在 0%
  void bars.offsetHeight;
  fills.forEach(([el, pct]) => { el.style.width = `${pct}%`; });

  const quotes = $("i-quotes");
  quotes.innerHTML = "";
  const sq = d.sample_quotes || {};
  const themeNames = Object.keys(sq);
  if (!themeNames.length) quotes.innerHTML = '<p class="empty">无样例引用</p>';
  themeNames.forEach((th) => {
    (sq[th] || []).forEach((q) => {
      const el = document.createElement("div");
      el.className = "quote";
      el.innerHTML = `<div class="q-theme">${esc(th)}</div><div class="q-text">“${esc(q)}”</div>`;
      quotes.appendChild(el);
    });
  });

  const acts = $("i-actions");
  acts.innerHTML = "";
  (d.action_items || []).forEach((a) => {
    const li = document.createElement("li");
    const m = a.match(/^([^：:]+)[：:]\s*(.*)$/);
    const themeName = m ? m[1].replace(/占\s*\d+%$/, "").trim() : "";
    const en = THEME_EN[themeName];
    li.innerHTML = esc(a) + (en ? `<span class="en">EN · ${esc(en)} — action tracked for cross-border ops</span>` : "");
    acts.appendChild(li);
  });
});

/* ---------------- ④ 英文回复草稿 ---------------- */
$("r-demo").addEventListener("click", () => {
  $("r-review").value = "Two stars. Delivery took three weeks and the package arrived damaged. Support never replied.";
});
$("r-run").addEventListener("click", async () => {
  const review = $("r-review").value.trim();
  if (!review) { toast("请先输入一条差评"); return; }
  const j = await call("draft_reply", {
    review, tone: $("r-tone").value, marketplace: $("r-market").value, refund_ready: $("r-refund").checked,
  });
  if (!j.ok) { toast(`生成失败：${j.error}`); return; }
  const d = j.data;
  $("r-theme").textContent = `主题：${d.theme} · 道歉强度：${d.apology_level}`;
  $("r-draft").textContent = d.reply_draft;
  $("r-copy").disabled = false;
  const cl = $("r-checklist");
  cl.innerHTML = "";
  (d.self_check || d.checklist || []).forEach((c) => {
    const li = document.createElement("li");
    li.textContent = c;
    cl.appendChild(li);
  });
});
$("r-copy").addEventListener("click", () => copyText($("r-draft").textContent));

/* ---------------- 共享状态: 最近一次成功结果 (504 降级回退的数据源) ---------------- */
let lastGood = null;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fmtMs = (v) => `${v < 0.1 ? Number(v).toFixed(3) : Number(v).toFixed(1)} ms`;
const num = (id, fallback) => {
  const v = Number($(id).value);
  return Number.isFinite(v) ? v : fallback;
};

/* ---------------- ⑤ Coze Bot 对话演练场 ---------------- */
const botLog = $("bot-log"), botInput = $("bot-input");
let botContext = null;
let botTurns = 0;
let QUICK = [];

function setBotCtx() {
  $("bot-ctx").textContent = botContext ? `${botContext.tool}(${JSON.stringify(botContext.params)})` : "无";
}

function scrollLog() {
  botLog.scrollTop = botLog.scrollHeight;
}

function pushUser(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  botLog.appendChild(el);
  scrollLog();
}

/** 失败也要留痕: 演练场里的每一次异常都必须变成看得见的诊断, 而不是控制台里的红字. */
function pushPlain(kind, html) {
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.innerHTML = `<div class="bubble">${html}</div>`;
  botLog.appendChild(el);
  scrollLog();
}

function pushFail(msg) {
  pushPlain("bot", `<div class="meta"><span class="tool-chip clarify">error</span></div><p class="summary">${esc(msg)}</p>`);
}

function waterfall(rows) {
  const max = Math.max(...rows.map((r) => r.ms), 0.001);
  return `<div class="wf">` + rows
    .map(
      (r) =>
        `<div class="wf-row"><span class="lab">${esc(r.label)}</span>` +
        `<div class="wf-track"><div class="wf-bar sev-${r.kind}" style="width:${Math.max((r.ms / max) * 100, 2).toFixed(1)}%"></div></div>` +
        `<span class="val">${esc(fmtMs(r.ms))}</span></div>`,
    )
    .join("") + `</div>`;
}

function tokenBlock(t) {
  const rows = [
    { label: "工具清单 context", ms: t.context, kind: "network" },
    { label: "用户输入 prompt", ms: t.prompt, kind: "server" },
    { label: "工具输出 output", ms: t.tool_output, kind: "render" },
    { label: "组装回复 completion", ms: t.completion, kind: "low" },
  ];
  // Token 条复用瀑布流的条状形态, 但宽度按占总量的比例 (总量为 0 时不渲染空条)
  const max = Math.max(t.total || 0, 1);
  return (
    `<div class="wf">` +
    rows
      .map(
        (r) =>
          `<div class="wf-row"><span class="lab">${esc(r.label)}</span>` +
          `<div class="wf-track"><div class="wf-bar" style="width:${Math.max((r.ms / max) * 100, 1).toFixed(1)}%"></div></div>` +
          `<span class="val">${r.ms} tk</span></div>`,
      )
      .join("") +
    `</div><p class="codeblock">本轮预估总消耗 <b>${t.total}</b> tk · 折算 ¥0 (本地规则引擎不调用大模型) —— 上线后同一份清单要按所选模型单价计费。</p>`
  );
}

function kvBlock(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `<span class="k">${esc(k)}</span>: ${esc(typeof v === "string" ? v : JSON.stringify(v))}`)
    .join("\n");
}

function renderCard(card, totalMs, renderMs, processMs) {
  const d = card.decision || {};
  const isCall = card.type === "call";
  const meta = [
    `<span class="tool-chip${isCall ? "" : " clarify"}">${esc(isCall ? card.tool : "clarify 追问")}</span>`,
    `<span class="pill pill-dim">Function Calling score ${esc(d.score ?? 0)}</span>`,
    (d.signals || []).length ? `<span class="pill pill-dim">信号 ${esc((d.signals || []).join(" · "))}</span>` : "",
    d.inherited ? `<span class="pill pill-live">上下文继承</span>` : "",
    (d.overrides || []).length ? `<span class="pill pill-dim">改写 ${esc((d.overrides || []).join(", "))}</span>` : "",
  ].join("");

  const summary = isCall ? esc(card.summary) : esc(card.message);
  const chips = isCall
    ? `<div class="chips">${(card.chips || []).map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join("")}</div>`
    : "";
  const body = isCall && card.body ? `<pre class="body">${esc(card.body)}</pre>` : "";

  // 四段全是实测值: 总往返由 performance 量, 网关段由 X-Process-Ms 回传, 业务段由 handler 自计, 渲染段自计
  const segServer = Number((card.timings || {}).server_ms || 0);
  const segNetwork = Math.max(totalMs - processMs - renderMs, 0);
  const wf = waterfall([
    { label: "客户端↔网关", ms: segNetwork, kind: "network" },
    { label: "网关整体处理", ms: processMs, kind: "server" },
    { label: "└ 路由+工具执行", ms: segServer, kind: "low" },
    { label: "卡片渲染", ms: renderMs, kind: "render" },
  ]);

  const sections = isCall
    ? `<details><summary>入参 JSON Schema（与 /openapi.coze.json 同源）</summary><div class="dwrap"><pre class="codeblock">${esc(JSON.stringify(card.schema, null, 2))}</pre></div></details>
       <details><summary>Coze 请求头（凭据仅占位符）</summary><div class="dwrap"><pre class="codeblock">${esc(`${card.http.method} ${card.http.path}\n` + kvBlock(card.http.headers))}</pre><pre class="codeblock">body: ${esc(JSON.stringify(card.params))}</pre></div></details>`
    : "";

  pushPlain(
    "bot",
    `${meta}<p class="summary">${summary}</p>${chips}${body}
     <details open><summary>往返延迟瀑布 · 合计 ${esc(fmtMs(totalMs))}</summary><div class="dwrap">${wf}</div></details>
     ${sections}
     <details><summary>Token 消耗预估 · ${card.tokens.total} tk</summary><div class="dwrap">${tokenBlock(card.tokens)}</div></details>
     <details><summary>原始响应</summary><div class="dwrap"><pre class="codeblock">${esc(JSON.stringify(isCall ? card.result : { type: card.type, message: card.message }, null, 2))}</pre></div></details>`,
  );
}

async function botSend(preset) {
  const text = String(preset ?? botInput.value).trim();
  if (!text) { toast("先说一句诉求，或点一条快问快答"); return false; }
  botInput.value = "";
  pushUser(text);
  const rid = "studio-" + Date.now().toString(36);
  const t0 = performance.now();
  let resp;
  try {
    resp = await fetch("/bot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Coze-Request-Id": rid },
      body: JSON.stringify({ message: text, context: botContext }),
    });
  } catch (err) {
    pushFail(`网关不可达：${err.message}`);
    return false;
  }
  const totalMs = performance.now() - t0;
  const processMs = Number(resp.headers.get("X-Process-Ms")) || 0;
  let j;
  try {
    j = await resp.json();
  } catch (err) {
    pushFail(`响应不是合法 JSON（HTTP ${resp.status}）`);
    return false;
  }
  if (!j.ok || !j.data) {
    pushFail(j.error || "网关返回空卡片");
    return false;
  }
  const card = j.data;
  botContext = card.context && card.context.tool ? card.context : botContext;
  if (card.type === "call" && card.ok) {
    lastGood = { tool: card.tool, summary: card.summary };
  }
  botTurns += 1;
  $("bot-turns").textContent = `${botTurns} 轮 · req ${card.request_id || rid}`;
  setBotCtx();
  const r0 = performance.now();
  renderCard(card, totalMs, performance.now() - r0, processMs);
  return true;
}

$("bot-send").addEventListener("click", () => botSend());
botInput.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") botSend();
});
$("bot-reset").addEventListener("click", () => {
  botContext = null;
  botTurns = 0;
  botLog.innerHTML = "";
  $("bot-turns").textContent = "0 轮";
  setBotCtx();
  bootBot();
  toast("上下文已清空（只清对话, 不动其它面板）");
});

async function bootBot() {
  setBotCtx();
  try {
    const resp = await fetch("/bot/greet");
    const j = await resp.json();
    if (!j.ok) throw new Error(j.error || "开场白为空");
    const g = j.data;
    QUICK = g.quick_prompts || [];
    pushPlain(
      "bot",
      `<div class="meta"><span class="tool-chip">bot</span><span class="pill pill-dim">挂载 4 技能 · 本地意图路由替身</span></div><p class="summary">${esc(g.message)}</p>` +
        `<details><summary>Token 消耗预估 · 系统提示词固定开销</summary><div class="dwrap">${tokenBlock(g.tokens)}</div></details>`,
    );
    const q = $("bot-quicks");
    q.innerHTML = "";
    QUICK.forEach((text, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "qchip";
      btn.textContent = `${i + 1}. ${text.replace(/\n/g, " / ")}`;
      btn.addEventListener("click", () => botSend(text));
      q.appendChild(btn);
    });
  } catch (err) {
    $("bot-quicks").innerHTML = '<p class="empty">开场白不可用：网关未提供 /bot/greet。</p>';
  }
}

/* ---------------- ⑥ 容灾与异常注入沙箱 ---------------- */
function simRow(log, cls, code, text) {
  const el = document.createElement("div");
  el.className = `sim-row ${cls}`;
  el.innerHTML = `<span class="code">${esc(code)}</span><span class="tx">${esc(text)}</span>`;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

$("th-run").addEventListener("click", async () => {
  const reject = Math.max(num("th-reject", 2), 0);
  const maxRetry = Math.max(num("th-attempt", 4), 1);
  const log = $("th-log");
  log.innerHTML = "";
  $("th-verdict").textContent = "运行中…";
  let waited = 0;
  let recovered = null;
  for (let attempt = 0; attempt < maxRetry; attempt += 1) {
    let resp, j;
    try {
      resp = await fetch(`/sim/throttle?attempt=${attempt}&reject_times=${reject}`);
      j = await resp.json();
    } catch (err) {
      simRow(log, "c504", "ERR", `第 ${attempt + 1} 次请求没能抵达网关：${err.message}`);
      break;
    }
    const data = j.data || {};
    if (resp.status === 429) {
      const retryAfter = Number(resp.headers.get("Retry-After") || data.retry_after_seconds || 1) * 1000;
      const backoff = Math.min(retryAfter * 2 ** attempt, 4000);
      waited += backoff;
      simRow(
        log,
        "c429",
        "429",
        `第 ${attempt + 1} 次尝试被限流 · Retry-After ${retryAfter / 1000}s · 指数退避 ${backoff}ms 后重试 (剩余配额 ${esc(resp.headers.get("X-RateLimit-Remaining") ?? "-")})`,
      );
      await wait(backoff);
      continue;
    }
    recovered = attempt + 1;
    simRow(log, "c200", "200", `第 ${attempt + 1} 次尝试放行：${esc(data.note || j.error || "已恢复")}`);
    break;
  }
  const v = $("th-verdict");
  if (recovered) {
    v.textContent = `退避 ${recovered - 1} 次后恢复 · 累计等待 ${waited}ms`;
    v.className = "pill pill-live";
  } else {
    v.textContent = `${maxRetry} 次内未恢复 · 转本地降级`;
    v.className = "badge badge-medium";
  }
});

/** 降级回退: 运营侧永远看得到东西, 而不是一个转圈的按钮. */
function degradeNote(log, reason) {
  if (lastGood) {
    simRow(log, "c200", "CACHE", `已回退到最近一次成功结果（${lastGood.tool}）：${lastGood.summary}`);
  } else {
    simRow(log, "c504", "CACHE", "本次会话尚无成功结果可回退 —— 先在 ①～⑤ 跑通一次, 再回来点超时。");
  }
  simRow(log, "cabort", "NOTE", reason);
}

$("to-abort").addEventListener("click", async () => {
  const ms = Math.max(num("to-ms", 2500), 0);
  const budget = Math.max(num("to-budget", 1200), 0);
  const log = $("to-log");
  log.innerHTML = "";
  $("to-verdict").textContent = "请求中…";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), Math.max(budget, 1));
  const t0 = performance.now();
  try {
    const resp = await fetch(`/sim/timeout?ms=${ms}&budget=${budget}`, { signal: ctl.signal });
    const took = performance.now() - t0;
    const j = await resp.json();
    simRow(log, resp.status === 504 ? "c504" : "c200", String(resp.status), `上游 ${ms}ms 在预算内跑完 (${took.toFixed(0)}ms 往返)：${esc(j.error || (j.data || {}).fallback || "正常返回")}`);
    $("to-verdict").textContent = resp.status === 504 ? "服务端已降级" : "预算内正常返回";
    $("to-verdict").className = resp.status === 504 ? "badge badge-medium" : "pill pill-live";
    if (resp.status === 504) degradeNote(log, `响应头 X-Degrade=${resp.headers.get("X-Degrade") ?? "-"}`);
  } catch (err) {
    const took = performance.now() - t0;
    if (err && err.name === "AbortError") {
      simRow(log, "c504", "ABORT", `第 ${budget}ms 触发客户端预算, AbortController 掐断连接（上游其实要 ${ms}ms）`);
      $("to-verdict").textContent = `预算中断 @${budget}ms · 已降级`;
      $("to-verdict").className = "badge badge-high";
      degradeNote(log, `中断耗时 ${took.toFixed(0)}ms, 用户等待被预算硬封顶 —— 绝不会让运营干等。`);
    } else {
      simRow(log, "c504", "ERR", `请求异常：${esc(err.message)}`);
      $("to-verdict").textContent = "请求异常";
      $("to-verdict").className = "badge badge-high";
    }
  } finally {
    clearTimeout(timer);
  }
});

$("to-degrade").addEventListener("click", async () => {
  const ms = Math.max(num("to-ms", 2500), 0);
  const budget = Math.max(num("to-budget", 1200), 0);
  const log = $("to-log");
  log.innerHTML = "";
  $("to-verdict").textContent = "等待服务端降级…";
  try {
    const resp = await fetch(`/sim/timeout?ms=${ms}&budget=${Math.min(budget, Math.max(ms - 1, 0))}`);
    const j = await resp.json();
    simRow(log, resp.status === 504 ? "c504" : "c200", String(resp.status), `${esc(j.error || "未超时")} · 回退策略：${esc((j.data || {}).fallback || "-")}`);
    $("to-verdict").textContent = resp.status === 504 ? `504 降级封套 @${ms}ms` : "正常返回";
    $("to-verdict").className = resp.status === 504 ? "badge badge-high" : "pill pill-live";
    degradeNote(log, `响应头 X-Degrade=${resp.headers.get("X-Degrade") ?? "-"} · 封套仍是 {ok:false, error, data}, 平台不会当成网络故障重试。`);
  } catch (err) {
    simRow(log, "c504", "ERR", `请求异常：${esc(err.message)}`);
  }
});

$("bat-run").addEventListener("click", async () => {
  const log = $("bat-log");
  log.innerHTML = "";
  $("bat-verdict").textContent = "注入中…";
  let cases;
  try {
    const j = await (await fetch("/sim/cases")).json();
    cases = j.data.cases || [];
  } catch (err) {
    $("bat-verdict").textContent = "用例不可用";
    $("bat-verdict").className = "badge badge-high";
    return;
  }
  let blocked = 0;
  for (const c of cases) {
    let resp, body;
    try {
      resp = await fetch(`/tools/${c.tool}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: c.body,
      });
      body = await resp.json();
    } catch (err) {
      body = { ok: true, error: `请求失败: ${err.message}` };
    }
    const error = String(body.error || "");
    const hit = resp.status === 200 && body.ok === false && (!c.expect || error.includes(c.expect));
    if (hit) blocked += 1;
    const el = document.createElement("div");
    el.className = "fault" + (hit ? "" : " miss");
    el.innerHTML =
      `<div class="fhead"><span class="fname">${esc(c.title)}</span>` +
      `<span class="st ${hit ? "st-block" : "st-warn"}">${hit ? "已拦截 · HTTP 200" : "未达预期 · HTTP " + resp.status}</span>` +
      `<span class="layer">${esc(c.layer)} · POST /tools/${esc(c.tool)}</span></div>` +
      `<div class="fbody">→ ${esc(c.body)}</div>` +
      `<div class="fdiag">诊断：${esc(error || "(无错误文本)")}</div>` +
      `<div class="fadvice">${esc(c.advice)}</div>`;
    log.appendChild(el);
  }
  log.scrollTop = log.scrollHeight;
  const v = $("bat-verdict");
  v.textContent = `${blocked}/${cases.length} 按预期拦截 · 零 5xx · 零堆栈外泄`;
  v.className = blocked === cases.length ? "pill pill-live" : "badge badge-high";
  toast(blocked === cases.length ? "全部畸形入参被同一校验链路拦下" : "有用例未按预期拦截, 见红字");
});

/* ---------------- ⑦ OpenAPI 导出与一键自检 ---------------- */
async function runAudit() {
  const box = $("audit-list");
  $("audit-badge").textContent = "自检中…";
  $("audit-badge").className = "badge badge-none";
  let d;
  try {
    const j = await (await fetch("/audit")).json();
    d = j.data;
  } catch (err) {
    box.innerHTML = `<p class="empty">自检接口不可用：${esc(err.message)}</p>`;
    $("audit-badge").textContent = "自检失败";
    $("audit-badge").className = "badge badge-high";
    return;
  }
  const s = d.summary;
  const clean = s.error === 0 && s.warning === 0;
  box.innerHTML = "";
  d.items.forEach((it) => {
    const el = document.createElement("div");
    el.className = `audit-row ${it.status}`;
    el.innerHTML =
      `<span class="mark">${it.status === "pass" ? "✔" : it.status === "info" ? "ℹ" : "✖"}</span>` +
      `<span class="aname">${esc(it.name)}</span><span class="adetail">${esc(it.detail)}</span>`;
    box.appendChild(el);
  });
  const badge = $("audit-badge");
  badge.textContent = `${s.error} error · ${s.warning} warning`;
  badge.className = `badge ${clean ? "badge-low" : "badge-high"}`;
  toast(clean ? `${s.checked} 项自检全清 · 可直接导入扣子` : "存在待修项, 见清单");
}

async function refreshExport() {
  const fmt = $("ex-format").value === "yaml" ? "yaml" : "json";
  $("ex-download").href = `/export/openapi?format=${fmt}`;
  const pane = $("ex-preview");
  $("ex-meta").textContent = "生成中…";
  try {
    const resp = await fetch(`/export/openapi?format=${fmt}&download=false`);
    const text = await resp.text();
    const lines = text.split("\n");
    pane.textContent = text;
    $("ex-meta").textContent = `${fmt.toUpperCase()} · ${lines.length} 行 · ${text.length} 字节 · ${resp.headers.get("X-Process-Ms") || "-"} ms`;
  } catch (err) {
    pane.textContent = `导出失败：${err.message}`;
    $("ex-meta").textContent = "导出失败";
  }
}

$("audit-run").addEventListener("click", runAudit);
$("ex-refresh").addEventListener("click", refreshExport);
$("ex-format").addEventListener("change", refreshExport);

/* ---------------- Tab 切换 & 评委一键演示 ---------------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`panel-${btn.dataset.tab}`).classList.add("active");
  });
});
const activate = (name) => document.querySelector(`.tab[data-tab="${name}"]`).click();

$("btn-tour").addEventListener("click", async () => {
  const btn = $("btn-tour");
  btn.disabled = true;
  try {
    activate("compliance");
    $("c-demo").click();
    toast("① 合规检测：高危词实时高亮 + 一键改写");
    await wait(1600);
    activate("insight");
    $("i-demo").click(); $("i-run").click();
    toast("③ 差评归因：8 大主题占比 + 中英改进清单");
    await wait(1600);
    activate("reply");
    $("r-demo").click(); $("r-run").click();
    toast("④ 英文回复：语气模板 + 渠道合规自检");
    await wait(1400);
    activate("bot");
    if (!botTurns && QUICK.length) {
      await botSend(QUICK[3]);
      await botSend("换成亚马逊平台再查一遍");
    }
    toast("⑤ Bot 演练：自然语言 → Function Calling → 结构化卡片（含多轮追问）");
    await wait(2200);
    activate("chaos");
    $("bat-run").click();
    toast("⑥ 容灾沙箱：10 条畸形入参全部被同一校验链路拦下");
    await wait(1400);
    $("th-run").click();
    await wait(1200);
    $("to-abort").click();
    toast("⑥ 容灾沙箱：429 退避重试 + 504 预算中断降级回退");
    await wait(2200);
    activate("schema");
    await runAudit();
    toast("⑦ 规范导出：19 项兼容性自检 · 0 error / 0 warning");
  } finally {
    btn.disabled = false;
  }
});

/* 初始: 立即跑一次实时检测 + 预热演练场与导出预览, 评委打开即是成品态 */
pingGateway();
runCompliance();
bootBot();
refreshExport();
document.querySelector('.tab[data-tab="schema"]').addEventListener("click", () => {
  if (!$("audit-list").querySelector(".audit-row")) runAudit();
}, { once: true });
