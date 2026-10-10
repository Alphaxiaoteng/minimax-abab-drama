/* Plugin Debugger Studio — 直连同进程网关, 与扣子调用完全同一条链路 (POST /tools/{name}). */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
  orig.innerHTML = html;
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
  $("s-theme").textContent = (d.themes || []).length;

  const bars = $("i-bars");
  bars.innerHTML = "";
  (d.themes || []).forEach((t) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    const pct = Math.round((t.ratio || 0) * 100);
    row.innerHTML =
      `<div class="lab"><span>${esc(t.theme)} <i class="sev-dot sev-${esc(t.severity || "low")}"></i></span>` +
      `<span class="meta">${t.count} 条 · ${pct}%</span></div>` +
      `<div class="track"><div class="fill sev-${esc(t.severity || "low")}" style="width:0%"></div></div>`;
    bars.appendChild(row);
    requestAnimationFrame(() => { row.querySelector(".fill").style.width = pct + "%"; });
  });

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
  activate("compliance");
  $("c-demo").click();
  toast("① 合规检测：高危词实时高亮 + 一键改写");
  await new Promise((r) => setTimeout(r, 1600));
  activate("insight");
  $("i-demo").click(); $("i-run").click();
  toast("③ 差评归因：8 大主题占比 + 中英改进清单");
  await new Promise((r) => setTimeout(r, 1600));
  activate("reply");
  $("r-demo").click(); $("r-run").click();
  toast("④ 英文回复：语气模板 + 渠道合规自检");
});

/* 初始: 立即跑一次实时检测, 评委打开即是成品态 */
pingGateway();
runCompliance();
