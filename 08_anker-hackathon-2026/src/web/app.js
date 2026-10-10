/* Anker 智能用电管家 — 仪表盘逻辑,零依赖原生 JS。
 * 数据驱动:拉取 /api/*,渲染 SVG 图表 + 明细表 + AI 面板 + SSE 实时流。
 * 任何 fetch 失败都在 error_box 显式提示,页面永不空白。
 */
(function () {
  "use strict";

  var TIER_COLOR = {
    sharp_peak: "#ef4444",
    peak: "#f59e0b",
    flat: "#64748b",
    valley: "#38bdf8",
    deep_valley: "#22c55e"
  };
  var TIER_CN = {
    sharp_peak: "尖峰", peak: "峰", flat: "平", valley: "谷", deep_valley: "深谷"
  };
  var ACTION_CN = {
    charge: "充电", discharge: "放电", idle: "待机", export: "上网", hold: "保电"
  };

  var state = {
    tariffs: {},      // city -> tariff payload
    plan: null,       // last plan payload
    liveTimer: null,
    eventSource: null,
    liveHistory: []   // rolling SiteReading rows
  };

  function el(id) { return document.getElementById(id); }

  function showError(msg) {
    var box = el("error_box");
    box.style.display = "block";
    box.textContent = "⚠ " + msg;
  }
  function clearError() { el("error_box").style.display = "none"; }

  function fmt(n, d) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    d = d === undefined ? 2 : d;
    return Number(n).toFixed(d);
  }

  // ------------------------------------------------------------------ fetch
  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          var detail = t;
          try { var j = JSON.parse(t); if (j.detail) detail = JSON.stringify(j.detail); } catch (e) {}
          throw new Error(url + " → HTTP " + r.status + ": " + detail);
        });
      }
      return r.json();
    });
  }

  // ------------------------------------------------------------------ meta
  function loadMeta() {
    return Promise.all([
      getJSON("/api/health").catch(function (e) { showError("health: " + e.message); return { models: [], cities: [] }; }),
      getJSON("/api/tariffs").catch(function (e) { showError("tariffs: " + e.message); return {}; }),
      getJSON("/api/hardware").catch(function (e) { showError("hardware: " + e.message); return { models: [] }; })
    ]).then(function (res) {
      var health = res[0], tariffs = res[1], hardware = res[2];
      state.tariffs = tariffs;

      var citySel = el("city");
      citySel.innerHTML = "";
      var cities = Object.keys(tariffs).sort();
      cities.forEach(function (c) {
        var o = document.createElement("option");
        o.value = c; o.textContent = c;
        if (c === "shenzhen") o.selected = true;
        citySel.appendChild(o);
      });
      if (!cities.length) {
        (health.cities || []).forEach(function (c) {
          var o = document.createElement("option"); o.value = c; o.textContent = c; citySel.appendChild(o);
        });
      }

      var modelSel = el("model");
      modelSel.innerHTML = "";
      (hardware.models || []).forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.model;
        o.textContent = m.model + " · " + fmt(m.capacity_kwh, 2) + "kWh";
        if (m.model === "SOLIX_F3800") o.selected = true;
        modelSel.appendChild(o);
      });

      el("status_text").textContent = health.llm_available ? "就绪 · LLM 可用" : "就绪 · LLM 离线";
      return null;
    });
  }

  // ------------------------------------------------------------------ plan
  function buildPlanQuery() {
    var risk = parseInt(el("risk_slider").value, 10) / 10;
    var params = new URLSearchParams({
      city: el("city").value,
      model: el("model").value,
      mode: el("mode").value,
      weather: el("weather").value,
      risk_aversion: String(risk),
      reserve_soc: "0.10",
      use_llm: el("use_llm").checked ? "true" : "false"
    });
    return "/api/plan?" + params.toString();
  }

  function replan() {
    var btn = el("replan_btn");
    btn.disabled = true;
    btn.textContent = "调度中…";
    el("status_text").textContent = "求解中…";
    clearError();
    getJSON(buildPlanQuery()).then(function (plan) {
      state.plan = plan;
      renderKPI(plan);
      renderChart(plan);
      renderTable(plan);
      renderAI(plan);
      el("status_text").textContent = plan.solver_status === "optimal" ? "就绪 · 最优解" : "就绪 · " + (plan.solver_status || "—");
    }).catch(function (e) {
      showError("调度失败: " + e.message);
      el("status_text").textContent = "错误";
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "重新调度";
    });
  }

  // ------------------------------------------------------------------ KPI
  function renderKPI(p) {
    el("kpi_savings_cny").textContent = "¥" + fmt(p.savings_cny, 2);
    el("kpi_savings_pct").textContent = fmt(p.savings_pct, 1) + "%";
    el("kpi_baseline").innerHTML = "¥" + fmt(p.baseline_cost_cny, 2);
    el("kpi_optimized").innerHTML = "¥" + fmt(p.optimized_cost_cny, 2);
    el("kpi_selfcons").textContent = fmt((p.pv_self_consumption || 0) * 100, 1) + "%";
    el("kpi_cycles").textContent = fmt(p.cycles_used, 2) + " 次";
    var st = el("kpi_status");
    st.textContent = p.solver_status || "—";
    st.style.color = p.solver_status === "optimal" ? "var(--green)" : "var(--amber)";
  }

  // ------------------------------------------------------------------ chart
  function renderChart(p) {
    var svg = el("main_svg");
    var W = 960, H = 380;
    var mL = 46, mR = 46, mT = 24, mB = 40;
    var pw = W - mL - mR, ph = H - mT - mB;
    var points = (p.points || []).slice().sort(function (a, b) { return a.hour - b.hour; });
    if (!points.length) { svg.innerHTML = '<text x="' + W / 2 + '" y="' + H / 2 + '" fill="#8aa0c0">无调度数据</text>'; return; }

    var city = p.city || el("city").value;
    var curve = (state.tariffs[city] && state.tariffs[city].curve) || [];

    var xOf = function (hour) { return mL + (hour / 24) * pw; };
    var maxP = 0.001;
    var maxBatt = 0.001;
    points.forEach(function (d) {
      maxP = Math.max(maxP, d.load_kw || 0, d.pv_kw || 0, Math.abs(d.battery_kw || 0), Math.abs(d.grid_kw || 0));
      maxBatt = Math.max(maxBatt, Math.abs(d.battery_kw || 0));
    });
    var prices = curve.map(function (c) { return c.price; });
    var minPrice = prices.length ? Math.min.apply(null, prices) : 0;
    var maxPrice = prices.length ? Math.max.apply(null, prices) : 1;
    if (maxPrice <= minPrice) maxPrice = minPrice + 1;

    var yOfP = function (kw) { return mT + ph - (kw / maxP) * ph; };
    var yOfPrice = function (pr) { return mT + ph - ((pr - minPrice) / (maxPrice - minPrice)) * ph; };
    var yOfSoc = function (soc) { return mT + ph - soc * ph; };

    var s = "";

    // tier bands (shaded by tier color)
    if (curve.length) {
      for (var i = 0; i < curve.length; i++) {
        var c0 = curve[i];
        var x1 = xOf(c0.hour), x2 = xOf((i + 1 < curve.length ? curve[i + 1].hour : 24));
        s += rect(x1, mT, Math.max(0.5, x2 - x1), ph, TIER_COLOR[c0.tier] || "#64748b", 0.08);
      }
    }

    // axes
    s += '<line x1="' + mL + '" y1="' + (mT + ph) + '" x2="' + (mL + pw) + '" y2="' + (mT + ph) + '" stroke="#24344f"/>';
    s += '<line x1="' + mL + '" y1="' + mT + '" x2="' + mL + '" y2="' + (mT + ph) + '" stroke="#24344f"/>';
    s += '<line x1="' + (mL + pw) + '" y1="' + mT + '" x2="' + (mL + pw) + '" y2="' + (mT + ph) + '" stroke="#24344f"/>';
    for (var h = 0; h <= 24; h += 3) {
      s += '<text x="' + xOf(h) + '" y="' + (H - 16) + '" fill="#8aa0c0" font-size="10" text-anchor="middle">' + h + ':00</text>';
    }
    // left axis labels (power)
    s += '<text x="' + (mL - 8) + '" y="' + (mT + 4) + '" fill="#8aa0c0" font-size="10" text-anchor="end">' + fmt(maxP, 1) + '</text>';
    s += '<text x="' + (mL - 8) + '" y="' + (mT + ph) + '" fill="#8aa0c0" font-size="10" text-anchor="end">0 kW</text>';
    // right axis labels (price)
    s += '<text x="' + (mL + pw + 6) + '" y="' + (mT + 4) + '" fill="#f59e0b" font-size="10">' + fmt(maxPrice, 2) + '</text>';
    s += '<text x="' + (mL + pw + 6) + '" y="' + (mT + ph) + '" fill="#f59e0b" font-size="10">' + fmt(minPrice, 2) + '</text>';
    s += '<text x="' + (mL + pw + 6) + '" y="' + (mT - 8) + '" fill="#f59e0b" font-size="9">元/kWh</text>';
    s += '<text x="' + (mL - 34) + '" y="' + (mT - 8) + '" fill="#8aa0c0" font-size="9">kW / SOC</text>';

    // PV area
    if (points.length) {
      var pvPath = "M" + xOf(points[0].hour) + " " + (mT + ph);
      points.forEach(function (d) { pvPath += " L" + xOf(d.hour + 0.5) + " " + yOfP(d.pv_kw || 0); });
      pvPath += " L" + xOf(points[points.length - 1].hour + 0.5) + " " + (mT + ph) + " Z";
      s += '<path d="' + pvPath + '" fill="' + "#22c55e" + '" fill-opacity="0.28" stroke="none"/>';
      s += '<path d="' + pvTopPath(points, xOf, yOfP) + '" fill="none" stroke="#22c55e" stroke-width="1.5"/>';
    }

    // battery bars (charge positive up from mid-band, discharge negative)
    points.forEach(function (d) {
      var bk = d.battery_kw || 0;
      var bw = pw / 24 * 0.5;
      var cx = xOf(d.hour + 0.5) - bw / 2;
      var mid = mT + ph;
      if (Math.abs(bk) > 0.001) {
        var hh = (Math.abs(bk) / maxP) * ph;
        s += rect(cx, mid - hh, bw, hh, bk > 0 ? "#38bdf8" : "#a78bfa", 0.85);
      }
    });

    // load line
    s += '<path d="' + linePath(points, function (d) { return d.load_kw || 0; }, xOf, yOfP) + '" fill="none" stroke="#e6edf7" stroke-width="1.8"/>';

    // price line (right axis)
    if (curve.length) {
      s += '<path d="' + curvePricePath(curve, xOf, yOfPrice) + '" fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-dasharray="4 2"/>';
    }

    // SOC line (0-100%)
    s += '<path d="' + linePath(points, function (d) { return d.soc || 0; }, xOf, yOfSoc) + '" fill="none" stroke="#a78bfa" stroke-width="2.2"/>';

    // hover hit zones
    points.forEach(function (d, idx) {
      var zx = xOf(d.hour), zw = pw / 24;
      s += '<rect class="hit" data-idx="' + idx + '" x="' + zx + '" y="' + mT + '" width="' + zw + '" height="' + ph + '" fill="transparent"/>';
    });

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.innerHTML = s;

    // legend
    el("legend").innerHTML = [
      legend("#e6edf7", "负荷 kW"),
      legend("#22c55e", "光伏 PV"),
      legend("#38bdf8", "电池充电"),
      legend("#a78bfa", "电池放电/SOC"),
      legend("#f59e0b", "电价 元/kWh")
    ].join("");

    // tooltip wiring
    var tip = el("tooltip");
    var wrap = el("chart_wrap");
    svg.querySelectorAll(".hit").forEach(function (r) {
      r.addEventListener("mousemove", function (ev) {
        var idx = parseInt(r.getAttribute("data-idx"), 10);
        var d = points[idx];
        var tierPrice = priceForHour(curve, d.hour, d.price);
        tip.innerHTML =
          '<div class="row"><b>' + d.hour + ':00</b><span>' + (TIER_CN[d.tier] || d.tier) + '</span></div>' +
          '<div class="row"><span>电价</span><span>¥' + fmt(tierPrice, 3) + '</span></div>' +
          '<div class="row"><span>负荷</span><span>' + fmt(d.load_kw) + ' kW</span></div>' +
          '<div class="row"><span>光伏</span><span>' + fmt(d.pv_kw) + ' kW</span></div>' +
          '<div class="row"><span>电池</span><span>' + fmt(d.battery_kw) + ' kW</span></div>' +
          '<div class="row"><span>电网</span><span>' + fmt(d.grid_kw) + ' kW</span></div>' +
          '<div class="row"><span>SOC</span><span>' + fmt((d.soc || 0) * 100, 1) + '%</span></div>' +
          '<div class="row"><span>动作</span><span>' + (ACTION_CN[d.action] || d.action) + '</span></div>';
        var rect = wrap.getBoundingClientRect();
        var x = ev.clientX - rect.left + 12;
        if (x > rect.width - 170) x = ev.clientX - rect.left - 170;
        tip.style.left = x + "px";
        tip.style.top = (ev.clientY - rect.top - 10) + "px";
        tip.style.display = "block";
      });
      r.addEventListener("mouseleave", function () { tip.style.display = "none"; });
    });
  }

  function priceForHour(curve, hour, fallback) {
    for (var i = 0; i < curve.length; i++) {
      if (curve[i].hour <= hour && hour < (i + 1 < curve.length ? curve[i + 1].hour : 24)) return curve[i].price;
    }
    return fallback;
  }

  function rect(x, y, w, h, fill, op) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" fill="' + fill + '" fill-opacity="' + op + '"/>';
  }
  function linePath(pts, getV, xOf, yOf) {
    var d = "";
    pts.forEach(function (p, i) {
      var x = xOf(p.hour + 0.5), y = yOf(getV(p));
      d += (i === 0 ? "M" : "L") + x + " " + y;
    });
    return d;
  }
  function pvTopPath(pts, xOf, yOf) {
    var d = "";
    pts.forEach(function (p, i) {
      var x = xOf(p.hour + 0.5), y = yOf(p.pv_kw || 0);
      d += (i === 0 ? "M" : "L") + x + " " + y;
    });
    return d;
  }
  function curvePricePath(curve, xOf, yOf) {
    var d = "";
    curve.forEach(function (c, i) {
      var x = xOf(c.hour), y = yOf(c.price);
      d += (i === 0 ? "M" : "L") + x + " " + y;
    });
    return d;
  }
  function legend(color, label) {
    return '<div class="item"><span class="swatch" style="background:' + color + '"></span>' + label + "</div>";
  }

  // ------------------------------------------------------------------ table
  function renderTable(p) {
    var tbody = el("schedule_table").querySelector("tbody");
    tbody.innerHTML = "";
    var points = (p.points || []).slice().sort(function (a, b) { return a.hour - b.hour; });
    points.forEach(function (d) {
      var tr = document.createElement("tr");
      var act = d.action || "idle";
      if (act === "charge") tr.className = "row-charge";
      else if (act === "discharge") tr.className = "row-discharge";
      else if (act === "hold") tr.className = "row-hold";
      tr.innerHTML =
        "<td>" + pad(d.hour) + ":00</td>" +
        "<td>" + (TIER_CN[d.tier] || d.tier) + "</td>" +
        "<td>" + fmt(d.price, 3) + "</td>" +
        "<td>" + fmt(d.load_kw) + "</td>" +
        "<td>" + fmt(d.pv_kw) + "</td>" +
        "<td>" + fmt(d.battery_kw) + "</td>" +
        "<td>" + fmt(d.grid_kw) + "</td>" +
        "<td>" + fmt((d.soc || 0) * 100, 0) + "%</td>" +
        '<td class="action-' + act + '">' + (ACTION_CN[act] || act) + "</td>" +
        "<td>" + fmt(d.cost_cny) + "</td>";
      tbody.appendChild(tr);
    });
  }
  function pad(h) { return (h < 10 ? "0" : "") + h; }

  // ------------------------------------------------------------------ AI panel
  function renderAI(p) {
    var source = p.source || (p.llm_used ? "llm" : "rule_fallback");
    var srcEl = el("ai_source");
    if (source === "llm") {
      srcEl.innerHTML = '<span class="badge badge-llm">LLM 策略</span>';
    } else {
      srcEl.innerHTML = '<span class="badge badge-fallback">规则回退</span>';
    }
    el("ai_model").textContent = p.llm_model || "—";

    var noteArea = el("llm_note_area");
    if (p.llm_note) {
      noteArea.textContent = "回退原因: " + p.llm_note;
    } else {
      noteArea.textContent = source === "llm" ? "LLM 在线优化策略已生效" : "规则策略(离线确定性)";
    }

    var items = (p.explain && p.explain.length ? p.explain : (p.rationale || []));
    var ul = el("ai_rationale");
    ul.innerHTML = "";
    if (!items.length) {
      var li = document.createElement("li"); li.textContent = "暂无解释"; ul.appendChild(li);
    }
    items.forEach(function (line) {
      var li = document.createElement("li"); li.textContent = line; ul.appendChild(li);
    });
  }

  // ------------------------------------------------------------------ live SSE
  function startLive() {
    stopLive();
    state.liveHistory = [];
    var es;
    try { es = new EventSource("/api/stream"); }
    catch (e) { showError("EventSource 不可用: " + e.message); return; }
    state.eventSource = es;

    es.onmessage = function (ev) {
      if (!ev.data || ev.data.indexOf("{") !== 0) return;
      var r;
      try { r = JSON.parse(ev.data); } catch (e) { return; }
      if (r.error) { showError("stream: " + r.error); return; }
      updateLive(r);
    };
    es.onerror = function () {
      // EventSource auto-reconnects; when the server ends the stream cleanly
      // the readyState becomes CLOSED — reopen so the demo keeps ticking.
      if (es.readyState === EventSource.CLOSED) {
        setTimeout(startLive, 1500);
      }
    };
  }
  function stopLive() {
    if (state.eventSource) { try { state.eventSource.close(); } catch (e) {} state.eventSource = null; }
  }

  function updateLive(r) {
    var soc = (r.soc || 0);
    el("live_soc_text").textContent = fmt(soc * 100, 0) + "%";
    // gauge arc: semicircle length ~ 188.5
    var arc = el("soc_arc_fg");
    if (arc) arc.setAttribute("stroke-dasharray", fmt(soc * 188.5, 1) + " 999");
    el("live_tier_price").textContent = (TIER_CN[r.tier] || r.tier) + " · ¥" + fmt(r.price, 3);
    el("live_pv").textContent = fmt(r.pv_kw) + " kW";
    el("live_load").textContent = fmt(r.load_kw) + " kW";
    el("live_grid").textContent = fmt(r.grid_kw) + " kW";
    var tempEl = el("live_temp");
    tempEl.textContent = fmt(r.temp_c, 1) + " °C";
    tempEl.className = (r.temp_c > 45) ? "temp-warn" : "";

    state.liveHistory.push(r);
    if (state.liveHistory.length > 120) state.liveHistory.shift();
    drawLiveChart();
  }

  function drawLiveChart() {
    var cv = el("live_chart");
    if (!cv || !cv.getContext) return;
    var ctx = cv.getContext("2d");
    var W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    var h = state.liveHistory;
    if (h.length < 2) return;
    // draw SOC (green), load (white), grid (blue) over rolling window
    var maxV = 0.001;
    h.forEach(function (r) { maxV = Math.max(maxV, Math.abs(r.grid_kw || 0), (r.load_kw || 0), (r.pv_kw || 0)); });
    var xStep = W / (h.length - 1);
    function series(getV, color) {
      ctx.beginPath();
      h.forEach(function (r, i) {
        var x = i * xStep, y = H - (getV(r) / maxV) * (H - 10) - 5;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.stroke();
    }
    series(function (r) { return r.load_kw || 0; }, "#e6edf7");
    series(function (r) { return r.pv_kw || 0; }, "#22c55e");
    series(function (r) { return r.grid_kw || 0; }, "#38bdf8");
    // SOC as faint dashed on its own 0-100% scale
    ctx.beginPath();
    h.forEach(function (r, i) {
      var x = i * xStep, y = H - (r.soc || 0) * (H - 10) - 5;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#a78bfa"; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.4; ctx.stroke(); ctx.setLineDash([]);
  }

  // ------------------------------------------------------------------ wiring
  function onRiskInput() {
    var v = parseInt(el("risk_slider").value, 10);
    var label = v <= 3 ? "激进" : (v >= 7 ? "保守" : "中");
    el("risk_val").textContent = label;
  }

  function init() {
    el("risk_slider").addEventListener("input", onRiskInput);
    el("replan_btn").addEventListener("click", replan);
    ["city", "model", "mode", "weather"].forEach(function (id) {
      el(id).addEventListener("change", replan);
    });
    el("use_llm").addEventListener("change", replan);
    loadMeta().then(function () {
      replan();
      startLive();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();