/* 初焰·钠宙 — AIDC 仿真控制台前端逻辑
 * 控件变更 → 防抖请求 GET /api/simulate → ECharts 实时重绘。
 */
(function () {
  "use strict";

  var C = {
    cyan: "#24d3ee", green: "#35d99a", amber: "#ffb454", red: "#ff6b7a",
    blue: "#4f8cff", violet: "#9d7bff", text: "#dbe7ff", dim: "#6d7f9e",
    grid: "rgba(94,148,255,0.12)"
  };

  /* TOU 时段着色（与 src/config.py TOU_WINDOWS 对齐） */
  var TOU_AREAS = [
    { span: [0, 7], name: "谷", color: "rgba(46,124,255,0.06)" },
    { span: [8, 10], name: "峰", color: "rgba(255,180,84,0.07)" },
    { span: [10, 11], name: "尖峰", color: "rgba(255,107,122,0.10)" },
    { span: [13, 19], name: "峰", color: "rgba(255,180,84,0.07)" },
    { span: [19, 21], name: "尖峰", color: "rgba(255,107,122,0.10)" },
    { span: [21, 23], name: "峰", color: "rgba(255,180,84,0.07)" }
  ];

  var el = function (id) { return document.getElementById(id); };
  var charts = {};
  var debounceTimer = null;

  function fmt(n, d) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function setStatus(cls, txt) {
    el("led").className = "led " + cls;
    el("sys-status").textContent = txt;
  }

  function initCharts() {
    if (!window.echarts) {
      setStatus("err", "ECharts 未加载（CDN 不可达）— 图表不可用，KPI 仍会更新");
      return false;
    }
    ["chart-load", "pue-gauge", "chart-battery", "chart-cost"].forEach(function (id) {
      charts[id] = echarts.init(el(id), null, { renderer: "canvas" });
    });
    window.addEventListener("resize", function () {
      Object.keys(charts).forEach(function (k) { charts[k].resize(); });
    });
    return true;
  }

  var AXIS = {
    axisLine: { lineStyle: { color: C.grid } },
    axisLabel: { color: C.dim, fontFamily: "Menlo, monospace", fontSize: 10 },
    splitLine: { lineStyle: { color: C.grid } }
  };

  function touMarkAreas() {
    return TOU_AREAS.map(function (t) {
      return [{ xAxis: t.span[0], itemStyle: { color: t.color } }, { xAxis: t.span[1] }];
    });
  }

  /* ---------- 图 1：24H 负荷与削峰曲线 ---------- */
  function drawLoad(data) {
    var s = data.series, lim = data.meta.grid_limit_kw;
    charts["chart-load"].setOption({
      animationDuration: 450,
      textStyle: { fontFamily: "PingFang SC, sans-serif" },
      tooltip: { trigger: "axis", backgroundColor: "#0b1322", borderColor: C.grid, textStyle: { color: C.text, fontSize: 12 },
        valueFormatter: function (v) { return fmt(v, 1) + " kW"; } },
      legend: { textStyle: { color: C.dim, fontSize: 11 }, top: 2, icon: "roundRect", itemWidth: 12, itemHeight: 4 },
      grid: { left: 58, right: 22, top: 42, bottom: 26 },
      xAxis: Object.assign({ type: "category", data: s.hours, boundaryGap: false, name: "h", nameTextStyle: { color: C.dim } }, AXIS, { splitLine: { show: false } }),
      yAxis: Object.assign({ type: "value", name: "kW", nameTextStyle: { color: C.dim } }, AXIS),
      series: [
        { name: "IT 负载", type: "line", data: s.it_kw, symbol: "none", lineStyle: { width: 0 }, stack: "load",
          areaStyle: { color: "rgba(79,140,255,0.20)" }, markArea: { silent: true, data: touMarkAreas() } },
        { name: "IT+制冷 总负荷", type: "line", data: s.grid_base_kw, symbol: "none",
          lineStyle: { color: C.blue, width: 1.6, type: "dashed" } },
        { name: "LP 后电网取电", type: "line", data: s.grid_opt_kw, symbol: "none", smooth: 0.15,
          lineStyle: { color: C.cyan, width: 2.4, shadowColor: "rgba(36,211,238,0.55)", shadowBlur: 9 },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(36,211,238,0.20)" }, { offset: 1, color: "rgba(36,211,238,0.02)" }] } } },
        { name: "并网点限额", type: "line", data: null, symbol: "none",
          markLine: { silent: true, symbol: "none", label: { color: C.red, fontSize: 10, formatter: "限额 {c} kW" },
            lineStyle: { color: C.red, type: "solid", width: 1.4 }, data: [{ yAxis: lim }] } }
      ]
    });
  }

  /* ---------- 图 2：PUE 仪表盘 ---------- */
  function pueColor(v) {
    if (v < 1.3) return C.green;
    if (v < 1.45) return C.amber;
    return C.red;
  }

  function drawPue(data) {
    var k = data.kpis;
    charts["pue-gauge"].setOption({
      animationDuration: 600,
      series: [{
        type: "gauge", min: 1.0, max: 1.6, radius: "92%", center: ["50%", "58%"],
        startAngle: 210, endAngle: -30, splitNumber: 6,
        progress: { show: true, width: 14, roundCap: true,
          itemStyle: { color: pueColor(k.avg_pue_opt) } },
        axisLine: { lineStyle: { width: 14, color: [[1, "rgba(94,148,255,0.14)"]] } },
        axisTick: { distance: -20, lineStyle: { color: C.dim } },
        splitLine: { distance: -24, length: 8, lineStyle: { color: C.dim, width: 1.6 } },
        axisLabel: { distance: -8, color: C.dim, fontSize: 10, fontFamily: "Menlo" },
        pointer: { itemStyle: { color: C.cyan }, length: "58%", width: 4 },
        anchor: { show: true, size: 10, itemStyle: { color: C.cyan } },
        title: { show: true, offsetCenter: [0, "30%"], color: C.dim, fontSize: 12 },
        detail: { valueAnimation: true, offsetCenter: [0, "-12%"], color: C.text, fontSize: 30, fontFamily: "Menlo",
          formatter: function (v) { return v.toFixed(4); } },
        data: [{ value: k.avg_pue_opt, name: "优化后均值 · ΔPUE " + (k.delta_pue >= 0 ? "+" : "") + k.delta_pue.toFixed(4) }]
      }, {
        type: "gauge", min: 1.0, max: 1.6, radius: "72%", center: ["50%", "58%"],
        startAngle: 210, endAngle: -30, showMidTick: false,
        axisLine: { lineStyle: { width: 3, color: [[1, "rgba(94,148,255,0.25)"]] } },
        axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
        pointer: { itemStyle: { color: C.blue }, length: "40%", width: 2 },
        detail: { show: false }, title: { show: false },
        data: [{ value: k.avg_pue_base, name: "" }]
      }]
    });
  }

  /* ---------- 图 3：削峰填谷功率柱状 + SOC ---------- */
  function drawBattery(data) {
    var s = data.series;
    var neg = s.charge_kw.map(function (v) { return -v; });
    charts["chart-battery"].setOption({
      animationDuration: 450,
      tooltip: { trigger: "axis", backgroundColor: "#0b1322", borderColor: C.grid, textStyle: { color: C.text, fontSize: 12 } },
      legend: { textStyle: { color: C.dim, fontSize: 11 }, top: 2 },
      grid: { left: 58, right: 52, top: 40, bottom: 26 },
      xAxis: Object.assign({ type: "category", data: s.hours }, AXIS, { splitLine: { show: false } }),
      yAxis: [
        Object.assign({ type: "value", name: "kW", nameTextStyle: { color: C.dim } }, AXIS),
        Object.assign({ type: "value", name: "SOC %", min: 0, max: 100, nameTextStyle: { color: C.dim } }, AXIS, { splitLine: { show: false } })
      ],
      series: [
        { name: "充电（填谷）", type: "bar", data: neg, stack: "p", barWidth: "55%",
          itemStyle: { color: C.violet, borderRadius: [0, 0, 2, 2] } },
        { name: "放电（削峰）", type: "bar", data: s.discharge_kw, stack: "p",
          itemStyle: { color: C.amber, borderRadius: [2, 2, 0, 0] } },
        { name: "SOC", type: "line", yAxisIndex: 1, data: s.soc_pct, symbol: "none", smooth: 0.2,
          lineStyle: { color: C.green, width: 1.8 } }
      ]
    });
  }

  /* ---------- 图 4：经济性分解条形 ---------- */
  function drawCost(data) {
    var k = data.kpis;
    charts["chart-cost"].setOption({
      animationDuration: 450,
      tooltip: { backgroundColor: "#0b1322", borderColor: C.grid, textStyle: { color: C.text },
        valueFormatter: function (v) { return "¥ " + fmt(v, 1); } },
      grid: { left: 92, right: 30, top: 14, bottom: 24 },
      xAxis: Object.assign({ type: "value", name: "元/日", nameTextStyle: { color: C.dim } }, AXIS),
      yAxis: Object.assign({ type: "category", data: ["储能老化折算", "需量电费节省", "电度电费(优化后)", "单日净节省"] }, AXIS, { splitLine: { show: false } }),
      series: [{
        type: "bar", barWidth: 16, label: { show: true, position: "right", color: C.text, fontSize: 11, fontFamily: "Menlo",
          formatter: function (p) { return (p.value < 0 ? "-¥ " : "¥ ") + fmt(Math.abs(p.value), 0); } },
        data: [
          { value: k.degradation_cost, itemStyle: { color: C.red, borderRadius: 3 } },
          { value: k.demand_saving_yuan, itemStyle: { color: C.amber, borderRadius: 3 } },
          { value: k.electricity_cost, itemStyle: { color: C.blue, borderRadius: 3 } },
          { value: k.saving_yuan, itemStyle: { color: C.green, borderRadius: 3 } }
        ]
      }]
    });
  }

  /* ---------- KPI 卡片 ---------- */
  function drawKpis(data) {
    var k = data.kpis, m = data.meta;
    if (data.status !== "optimal") {
      ["k-shave", "k-saving", "k-peak", "k-pue"].forEach(function (id) { el(id).textContent = "不可行"; });
      el("k-shave-foot").textContent = "限额内削峰无法达成";
      return;
    }
    el("k-shave").textContent = (Number(k.peak_shaved_ratio) * 100).toFixed(2) + "%";
    el("k-shave-foot").textContent = "削减 " + fmt(k.baseline_peak_kw - k.peak_grid_kw, 0) +
      " kW → 限额 " + fmt(m.grid_limit_kw, 0) + " kW";
    el("k-saving").textContent = "¥ " + fmt(k.saving_yuan, 0);
    el("k-saving-foot").textContent = "需量 ¥" + fmt(k.demand_saving_yuan, 0) +
      " · 老化 −¥" + fmt(k.degradation_cost, 0) + " · (" + Number(k.saving_pct).toFixed(2) + "%)";
    el("k-peak").textContent = fmt(k.peak_grid_kw, 0) + " kW";
    el("k-peak-foot").textContent = "基线 " + fmt(k.baseline_peak_kw, 0) + " kW · 负荷率 " + Number(k.load_factor).toFixed(3);
    el("k-pue").textContent = Number(k.avg_pue_opt).toFixed(4);
    el("k-pue-foot").textContent = "基线 " + Number(k.avg_pue_base).toFixed(4) +
      " · ΔPUE +" + Number(k.delta_pue).toFixed(4) + "（往返损耗）";
  }

  function showBanner(msg) {
    var b = el("banner");
    if (!msg) { b.classList.add("hidden"); return; }
    b.classList.remove("hidden");
    b.textContent = "⚠ " + msg;
  }

  /* ---------- 数据获取 ---------- */
  function params() {
    return {
      scenario: el("c-scenario").value,
      spike_multiplier: el("c-mult").value,
      battery: el("c-battery").value,
      tariff: el("c-tariff").value,
      c_rate: el("c-crate").value,
      price_spread: el("c-spread").value,
      degradation_weight: el("c-deg").value
    };
  }

  function qs(p) {
    return Object.keys(p).map(function (k) { return k + "=" + encodeURIComponent(p[k]); }).join("&");
  }

  function refresh() {
    setStatus("busy", "LP 求解中…");
    fetch("/api/simulate?" + qs(params()))
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        showBanner(data.status === "infeasible" ? ("LP 不可行：" + data.message) : null);
        if (data.status === "optimal" && charts["chart-load"]) {
          drawLoad(data); drawBattery(data); drawCost(data); drawPue(data);
        }
        drawKpis(data);
        lastData = data;
        if (data.status === "optimal") updateTwin();
        if (islandOn) startIsland(true);
        setStatus("ok", data.status === "optimal" ? "在线 · Optimal" : "在线 · Infeasible");
        el("solve-time").textContent = data.status === "optimal" ? ("solve " + data.kpis.solve_ms + " ms") : "";
      })
      .catch(function (e) {
        setStatus("err", "请求失败：" + e.message);
        showBanner("服务端请求失败（" + e.message + "），请确认 uvicorn 已启动。");
      });
  }

  /* ==========================================================
   * 机房热孪生：32 机柜 2.5D 网格 + PUE 设计带仪表 + 时间游标
   * 温度映射为演示标定 [INFERENCE]：rackT = 22 + 38h，h 为归一化热负荷
   * ========================================================== */
  var lastData = null;
  var rackEls = [];
  var scrubIdx = 56;
  var playing = false, playTimer = null;

  function heatColor(h) {
    var stops = [[41, 96, 158], [36, 211, 238], [255, 180, 84], [255, 96, 96]];
    var x = Math.max(0, Math.min(1, h)) * (stops.length - 1);
    var i = Math.min(Math.floor(x), stops.length - 2), f = x - i;
    var c = [0, 1, 2].map(function (j) {
      return Math.round(stops[i][j] + (stops[i + 1][j] - stops[i][j]) * f);
    });
    return "rgb(" + c.join(",") + ")";
  }

  function buildRackStage(racks) {
    var stage = el("rack-grid");
    stage.textContent = "";
    rackEls = racks.map(function (r) {
      var d = document.createElement("div");
      d.className = "rack" + (r.critical ? " crit" : "");
      d.title = r.id;
      stage.appendChild(d);
      return d;
    });
  }

  function hhmm(idx) {
    var t = idx * 0.25, h = Math.floor(t), m = Math.round((t - h) * 60);
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function updateTwin() {
    if (!lastData || lastData.status !== "optimal" || !lastData.thermal) return;
    var racks = lastData.thermal.racks;
    if (rackEls.length !== racks.length) buildRackStage(racks);

    var s = lastData.series;
    var itNow = s.it_kw[scrubIdx], coolNow = s.cooling_kw[scrubIdx];
    var itMax = Math.max.apply(null, s.it_kw);
    var wMax = Math.max.apply(null, racks.map(function (r) { return r.weight; }));
    var setp = lastData.thermal.cold_aisle_setpoint_c;
    var heatSum = 0;

    racks.forEach(function (r, i) {
      var kw = r.weight * itNow;
      var h = itMax > 0 ? kw / (wMax * itMax) : 0;
      heatSum += h;
      var d = rackEls[i];
      d.style.background = "linear-gradient(180deg, " + heatColor(h) +
        ", rgba(4,9,18,0.85) 130%)";
      d.title = r.id + (r.critical ? " ◆液冷训练" : "") + " · " + fmt(kw, 0) +
        " kW · " + (22 + 38 * h).toFixed(1) + "℃";
      d.classList.toggle("shed", islandOn && !r.critical);
      d.classList.toggle("island-on", islandOn && r.critical);
    });

    var avgH = heatSum / racks.length;
    var hotT = setp + 14 + 16 * avgH;
    el("t-cold").textContent = setp.toFixed(1) + "℃";
    el("t-hot").textContent = hotT.toFixed(1) + "℃";
    el("aisle-hot").style.background =
      "linear-gradient(90deg, " + heatColor(avgH * 0.55) + ", " +
      heatColor(avgH) + ", " + heatColor(avgH * 0.55) + ")";

    /* PUE 设计带 1.15~1.28（规划目标）+ 实测指针（诚实口径） */
    var pueNow = s.pue_opt[scrubIdx];
    var lo = 1.10, hi = 1.50;
    var band = lastData.thermal.pue_design_band;
    var zone = document.querySelector(".band-zone");
    zone.style.left = ((band[0] - lo) / (hi - lo) * 100).toFixed(1) + "%";
    zone.style.width = ((band[1] - band[0]) / (hi - lo) * 100).toFixed(1) + "%";
    var needle = el("band-needle");
    var x = Math.max(lo, Math.min(hi, pueNow));
    needle.style.left = ((x - lo) / (hi - lo) * 100).toFixed(1) + "%";
    var inBand = pueNow <= band[1];
    needle.style.background = inBand ? "#35d99a" : "#ff6b7a";
    needle.style.boxShadow = "0 0 10px " + (inBand ? "#35d99a" : "#ff6b7a");
    el("t-pue").textContent = Number(pueNow).toFixed(4);

    var shaved = islandOn ? 0 : (s.grid_base_kw[scrubIdx] - s.grid_opt_kw[scrubIdx]);
    el("twin-stats").textContent = "";
    var lines = [
      ["时刻", hhmm(scrubIdx)],
      ["IT 负载", fmt(itNow, 0) + " kW"],
      ["制冷", fmt(coolNow, 0) + " kW"],
      ["储能净出力", fmt(shaved, 0) + " kW"],
      ["液冷训练柜", racks.filter(function (r) { return r.critical; }).length + " / 32"]
    ];
    lines.forEach(function (row) {
      var p = document.createElement("div");
      p.appendChild(document.createTextNode(row[0] + " "));
      var b = document.createElement("b");
      b.textContent = row[1];
      p.appendChild(b);
      el("twin-stats").appendChild(p);
    });
    el("t-time").textContent = hhmm(scrubIdx);
    el("t-scrub").value = scrubIdx;
  }

  /* ==========================================================
   * Island Mode：市电跌落 → 10ms 切岛 → 关键机架续航倒计时
   * ========================================================== */
  var islandOn = false, islandData = null;
  var islandTimer = null, islandMin = 0, islandTotalMin = 0;

  function stopIsland() {
    islandOn = false;
    if (islandTimer) { clearInterval(islandTimer); islandTimer = null; }
    islandData = null;
    el("panel-island").classList.remove("live");
    el("island-live").classList.add("hidden");
    el("island-idle").classList.remove("hidden");
    el("i-tag").textContent = "待机";
    el("island-hint").textContent = "ISLAND 待机";
    el("island-hint").classList.remove("active");
    updateTwin();
  }

  function startIsland(silent) {
    var p = params();
    p.switch_hour = (scrubIdx * 0.25).toFixed(2);
    fetch("/api/island?" + qs(p))
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) {
        islandData = d; islandOn = true;
        if (!silent) { islandMin = 0; }
        islandTotalMin = d.endurance_min;
        el("island-idle").classList.add("hidden");
        el("island-live").classList.remove("hidden");
        el("panel-island").classList.add("live");
        el("i-tag").textContent = "孤网运行";
        el("island-hint").textContent = "ISLAND 10ms 已切入";
        el("island-hint").classList.add("active");
        renderIslandStatics(d);
        drawIslandChart();
        tickIsland();
        if (!islandTimer) islandTimer = setInterval(tickIsland, 250);
        updateTwin();
      })
      .catch(function (e) {
        el("i-warning").textContent = "岛网仿真失败：" + e.message;
      });
  }

  function renderIslandStatics(d) {
    var det = el("i-detail");
    det.textContent = "";
    [
      ["跌落时刻 " + fmt(d.switch_hour, 2) + "h 电网负荷", fmt(d.grid_load_at_switch_kw, 0) + " kW"],
      ["关键 GPU 机架 ×" + d.critical_racks, fmt(d.critical_load_kw, 0) + " kW 保障"],
      ["主动甩负荷（非关键）", "−" + fmt(d.shed_load_kw, 0) + " kW"],
      ["可用离网电量 @SOC " + Number(d.soc_at_switch_pct).toFixed(1) + "%", fmt(d.usable_energy_kwh, 0) + " kWh"],
      ["PCS 无缝切换", d.switchover_ms.toFixed(0) + " ms"]
    ].forEach(function (row) {
      var p = document.createElement("div");
      p.appendChild(document.createTextNode(row[0] + " · "));
      var b = document.createElement("b");
      b.textContent = row[1];
      p.appendChild(b);
      det.appendChild(p);
    });
    el("i-warning").textContent = d.warning ? ("⚠ " + d.warning) : "";
  }

  function tickIsland() {
    if (!islandData) return;
    var d = islandData;
    var soc0 = d.drain.soc_pct[0];
    var frac = islandTotalMin > 0 ? Math.min(1, islandMin / islandTotalMin) : 1;
    var soc = soc0 + (d.soc_min_pct - soc0) * frac;
    var curMin = Math.min(islandMin, d.drain.minutes[d.drain.minutes.length - 1]);
    var remain = Math.max(0, islandTotalMin - islandMin);
    var hh = Math.floor(remain / 60), mm = Math.floor(remain % 60);
    el("i-remain").textContent = remain > 0 ? (hh > 0 ? hh + "h" + (mm < 10 ? "0" : "") + mm + "m" : mm + " min") : "0 min";
    el("i-soc").textContent = soc.toFixed(1) + "%";
    if (remain <= 0 && islandTimer) {
      clearInterval(islandTimer); islandTimer = null;
      el("i-tag").textContent = "训练安全落盘";
      el("i-warning").textContent = "⚠ SOC 触及下限，关键训练已 checkpoint 落盘关机";
    }
    if (charts["chart-island"]) {
      charts["chart-island"].setOption({
        series: [{ markLine: { data: [{ xAxis: curMin }] } }]
      });
    }
    islandMin += 1;  /* 演示加速：250ms = 1 仿真分钟 */
  }

  function drawIslandChart() {
    if (!window.echarts || !islandData) return;
    if (!charts["chart-island"]) charts["chart-island"] = echarts.init(el("chart-island"));
    var d = islandData;
    charts["chart-island"].setOption({
      animationDuration: 300,
      tooltip: { trigger: "axis", backgroundColor: "#0b1322", borderColor: C.grid,
        textStyle: { color: C.text, fontSize: 11 } },
      grid: { left: 44, right: 16, top: 22, bottom: 24 },
      xAxis: Object.assign({ type: "category", data: d.drain.minutes, name: "min",
        nameTextStyle: { color: C.dim }, axisLabel: { color: C.dim, fontSize: 10 } }, {
        axisLine: { lineStyle: { color: C.grid } }, splitLine: { show: false } }),
      yAxis: Object.assign({ type: "value", name: "SOC %", min: 0, max: 100,
        nameTextStyle: { color: C.dim } }, AXIS, { splitLine: { show: true } }),
      series: [{
        type: "line", data: d.drain.soc_pct, symbol: "none", smooth: 0.1,
        lineStyle: { color: C.green, width: 2 },
        areaStyle: { color: "rgba(53,217,154,0.14)" },
        markLine: { silent: true, symbol: "none", label: { show: false },
          lineStyle: { color: C.amber, width: 1.4 }, data: [] }
      }],
      title: { text: "孤网 SOC 跌落曲线 · 带载 " + fmt(d.served_load_kw, 0) + " kW",
        left: 8, top: 2, textStyle: { color: C.dim, fontSize: 11, fontWeight: "normal" } }
    });
    charts["chart-island"].resize();
  }

  function bind() {
    ["c-scenario", "c-battery", "c-tariff"].forEach(function (id) {
      el(id).addEventListener("change", refresh);
    });
    function slider(id, outId, fmtFn) {
      var s = el(id);
      s.addEventListener("input", function () {
        el(outId).textContent = fmtFn(s.value);
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(refresh, 320);
      });
      el(outId).textContent = fmtFn(s.value);
    }
    slider("c-mult", "c-mult-out", function (v) { return Number(v).toFixed(2) + "×"; });
    slider("c-crate", "c-crate-out", function (v) { return Number(v).toFixed(2) + "C"; });
    slider("c-spread", "c-spread-out", function (v) {
      var n = Number(v) * 100; return (n > 0 ? "+" : "") + n.toFixed(0) + "%"; });
    slider("c-deg", "c-deg-out", function (v) { return Number(v).toFixed(1) + "×"; });

    el("t-scrub").addEventListener("input", function () {
      scrubIdx = Number(this.value);
      updateTwin();
    });
    el("t-play").addEventListener("click", function () {
      playing = !playing;
      this.classList.toggle("playing", playing);
      this.textContent = playing ? "⏸" : "▶";
      if (playing) {
        playTimer = setInterval(function () {
          scrubIdx = (scrubIdx + 1) % 96;
          updateTwin();
        }, 180);
      } else if (playTimer) { clearInterval(playTimer); playTimer = null; }
    });

    el("c-island").addEventListener("change", function () {
      if (this.checked) startIsland(true); else stopIsland();
    });
  }

  if (initCharts()) { bind(); refresh(); }
  else { bind(); refresh(); } /* 无图表时仍更新 KPI 与状态 */
})();
