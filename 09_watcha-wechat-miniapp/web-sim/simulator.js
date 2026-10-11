// 秒开 AI · H5 评委直测模拟器
// 目标：不装微信开发者工具，浏览器双击 index.html 即可完整把玩小程序。
// 铁律：所有分析都调用 engine.bundle.js 里的小程序同一份确定性内核（local-engine），
// 模拟器只做「渲染 + 交互复刻」，不另写任何假数据逻辑。

(function () {
  'use strict';

  var BOOT_T0 = performance.now();

  var WA = window.WA;
  var engine = WA.engine;
  var decode = WA.decode;

  // ===== Storage：localStorage 实现 getSync/setSync/removeSync，接口与 wx 适配器等价 =====
  function createWebStorage() {
    var PFX = 'wa-sim:';
    return {
      getSync: function (k) {
        try {
          var raw = localStorage.getItem(PFX + k);
          return raw == null ? null : JSON.parse(raw);
        } catch (e) { return null; }
      },
      setSync: function (k, v) {
        try { localStorage.setItem(PFX + k, JSON.stringify(v)); } catch (e) {}
      },
      removeSync: function (k) {
        try { localStorage.removeItem(PFX + k); } catch (e) {}
      }
    };
  }

  var storage = createWebStorage();
  var cache = WA.cache.createCache({ storage: storage, namespace: 'wa_recent', limit: 30 });

  // ===== 示例文本：与小程序 pages/quickread、pages/triage 的 buildSample 完全一致 =====
  var SAMPLE_QR = [
    '公司 2026 年第三季度经营情况说明',
    '本季度公司实现营业收入 128.6 亿元，同比增长 23.4%，环比增长 8.7%。',
    '归属于母公司股东的净利润为 15.7 亿元，同比增长 31.2%，净利率提升至 12.2%。',
    '毛利率为 38.1%，较去年同期提升 1.8 个百分点，主要来自高端产品占比提升。',
    '经营活动产生的现金流量净额为 22.3 亿元，同比增长 18.9%。',
    '研发投入 14.2 亿元，占营业收入比例 11.0%，同比增加 2.1 个百分点。',
    '海外业务收入 41.2 亿元，同比增长 26.5%，占总收入比重达到 32.0%。',
    '应收账款周转天数上升至 76 天，同比增加 9 天，需关注回款节奏放缓的风险。',
    '报告期内公司因产品质量问题被监管部门责令召回部分批次产品，涉及金额 1250 万元。',
    '同时公司面临原材料价格波动加剧与行业竞争加剧的压力，主要竞争对手已下调主力产品售价。',
    '公司预计第四季度收入增速将放缓至 15% 左右，并提示汇率波动可能带来汇兑损失。'
  ].join('\n');

  var SAMPLE_TR = [
    '紧急：报名 10 月 17 日小程序大赛截止前提交材料',
    '明天上午 9:00 参加 Q4 战略复盘会',
    '下午 3:00 与设计师评审秒开骨架屏',
    '回复张总邮件',
    '晚上 8:00 健身房锻炼',
    '给妈妈打电话（每周重复）',
    '顺便清理手机相册',
    '有空了解一下 uni-app 和原生小程序的差异',
    '不急，改天研究竞品新发布的版本',
    '整理上周路演反馈并归档',
    '周末可能考虑重构缓存模块',
    '更新一下个人主页的头像',
    '准备下周三客户签约提案'
  ].join('\n');

  // ===== DOM 小工具：全部 textContent 写入，杜绝注入 =====
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = String(text);
    return e;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) if (arguments[i]) parent.appendChild(arguments[i]);
    return parent;
  }

  var viewport = document.getElementById('viewport');
  var navTitle = document.getElementById('nav-title');
  var navBack = document.getElementById('nav-back');
  var tabbar = document.getElementById('tabbar');
  var toastBox = document.getElementById('toast');
  var toastTimer = null;

  function toast(msg) {
    toastBox.textContent = msg;
    toastBox.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastBox.classList.remove('on'); }, 1500);
  }

  // ===== 路由：tab 三页 + navigateTo 子页栈，复刻 switchTab/navigateTo/navigateBack =====
  var TABS = [
    { name: 'home', text: '首页', icon: '⌂' },
    { name: 'quickread', text: '一页纸', icon: '✎' },
    { name: 'triage', text: '断舍离', icon: '☰' }
  ];
  var NAV_TITLES = {
    home: '秒开 AI',
    quickread: '一页纸快读',
    triage: '日程断舍离',
    detail: '快读详情 · 追问',
    today: '今日安排'
  };

  var routeStack = [{ name: 'home', params: {} }];
  var inMemory = { quickread: null, triage: null }; // 当前会话最近结果（详情页兜底）
  var twTimer = null;

  function currentRoute() { return routeStack[routeStack.length - 1]; }

  function switchTab(name) {
    routeStack = [{ name: name, params: {} }];
    render();
  }
  function navigateTo(name, params) {
    stopTypewriter();
    routeStack.push({ name: name, params: params || {} });
    render();
  }
  function navigateBack() {
    if (routeStack.length <= 1) return;
    stopTypewriter();
    routeStack.pop();
    render(true);
  }

  function renderTabbar() {
    tabbar.innerHTML = '';
    var route = currentRoute();
    var counts = sceneCounts();
    TABS.forEach(function (t, idx) {
      var tab = el('div', 'tab' + (route.name === t.name ? ' active' : ''));
      add(tab, el('span', 'tab-icon', t.icon), el('span', null, t.text));
      var badgeN = idx === 1 ? counts.quickread : idx === 2 ? counts.triage : 0;
      if (badgeN > 0) {
        var badge = el('span', 'tab-badge', badgeN > 99 ? '99+' : String(badgeN));
        add(tab, badge);
      }
      tab.addEventListener('click', function () { switchTab(t.name); });
      tabbar.appendChild(tab);
    });
  }

  function sceneCounts() {
    var all = cache.rank();
    var triage = 0;
    all.forEach(function (r) { if (r.scene === 'triage') triage++; });
    return { quickread: all.length - triage, triage: triage };
  }

  // ===== 结果渲染：复刻 components/markdown-card 的投研排版 =====
  var KIND_TAG = { percent: '比率', amount: '金额', year: '年份', multiple: '倍数', delta: '变动' };
  var SEV_LABEL = { high: '红线', medium: '关注', low: '提示' };

  function section(title, bodyEl) {
    var s = el('div', 'md-section');
    add(s, el('div', 'md-section-bar'), el('div', 'md-section-title', title), bodyEl);
    return s;
  }

  function renderResearch(s) {
    var card = el('div', 'md-card content-enter');
    var head = el('div', 'md-head row-between');
    var tags = el('div', 'md-head-tags');
    if (s.format && s.format.label) add(tags, el('span', 'tag', s.format.label));
    add(tags, el('span', 'tag tag-offline', '离线分析'));
    add(head, el('span', 'md-head-title', '一页纸结果'), tags);
    add(card, head);

    if (s.conclusion) {
      add(card, section('一句话结论', el('div', 'md-plain', s.conclusion)));
    }

    if (s.keyData && s.keyData.length) {
      var grid = el('div', 'md-badges');
      s.keyData.slice(0, 9).forEach(function (d) {
        var top = el('div', 'md-badge-top');
        add(top, el('span', 'md-badge-value mono', d.value), el('span', 'md-badge-tag', KIND_TAG[d.kind] || '指标'));
        var b = el('div', 'md-badge');
        add(b, top, el('span', 'md-badge-label', d.label));
        b.title = d.evidence || '';
        add(grid, b);
      });
      add(card, section('关键财务指标', grid));
    }

    var cards = s.riskCards || [];
    if (cards.length) {
      var wrap = el('div');
      cards.forEach(function (c) {
        var box = el('div', 'md-risk ' + (c.severity === 'high' ? 'md-risk-high' : 'md-risk-med'));
        var head2 = el('div', 'md-risk-head');
        add(head2, el('span', 'md-risk-title', c.title), el('span', 'md-risk-sev', SEV_LABEL[c.severity] || '关注'));
        add(box, head2, el('div', 'md-risk-detail', c.detail));
        if (c.keywords && c.keywords.length) {
          var kws = el('div', 'md-risk-kws');
          c.keywords.forEach(function (kw) { add(kws, el('span', 'md-risk-kw', kw)); });
          add(box, kws);
        }
        add(wrap, box);
      });
      add(card, section('风险红线警示', wrap));
    }

    if (s.landscape && s.landscape.length) {
      var lw = el('div');
      s.landscape.forEach(function (l) {
        var lb = el('div', 'md-land');
        add(lb, el('div', 'md-land-text', l.text));
        var sig = el('div', 'md-land-signals');
        (l.signals || []).forEach(function (t) { add(sig, el('span', 'md-land-sig', t)); });
        add(lb, sig);
        add(lw, lb);
      });
      add(card, section('行业竞争格局', lw));
    }

    if (s.evidence && s.evidence.length) {
      var ew = el('div');
      s.evidence.forEach(function (e) { add(ew, el('div', 'md-quote', e.text)); });
      add(card, section('原文引用依据', ew));
      add(card, el('div', 'md-foot', '悬停指标徽章可看原文证据；全部数值真实抽取，未命中即留白。'));
    }
    return card;
  }

  function renderTriage(s) {
    var card = el('div', 'md-card content-enter');
    var head = el('div', 'md-head row-between');
    var tags = el('div', 'md-head-tags');
    add(tags, el('span', 'tag tag-offline', '离线分析'));
    add(head, el('span', 'md-head-title', '断舍离结果'), tags);
    add(card, head);

    if (s.today && s.today.length) {
      var tw = el('div');
      s.today.forEach(function (t, i) {
        var row = el('div', 'md-ordered');
        add(row, el('span', 'md-index', String(i + 1)), el('span', 'md-ordered-text', t.text || String(t)));
        add(tw, row);
      });
      add(card, section('今日必做', tw));
    }
    if (s.defer && s.defer.length) {
      var dw = el('div');
      s.defer.forEach(function (d) { add(dw, el('div', 'md-plain muted', d.text || String(d))); });
      add(card, section('可延后', dw));
    }
    if (s.deletions && s.deletions.length) {
      var rw = el('div');
      s.deletions.forEach(function (d) {
        var box = el('div', 'md-reason');
        add(box, el('span', 'md-reason-item', d.item), el('span', 'md-reason-why', d.reason));
        add(rw, box);
      });
      add(card, section('建议删除', rw));
    }
    if (s.timeBlocks && s.timeBlocks.length) {
      var bw = el('div');
      s.timeBlocks.forEach(function (b) {
        var row = el('div', 'md-block' + (b.type === 'break' ? ' md-block-break' : b.type === 'defer' ? ' md-block-defer' : ''));
        add(row, el('span', 'md-block-time', b.start + ' - ' + b.end), el('span', null, b.label));
        add(bw, row);
      });
      add(card, section('时间块', bw));
    }
    return card;
  }

  // ===== 打字机：与小程序 detail/today 页同一节奏（30ms/帧） =====
  function stopTypewriter() {
    if (twTimer) { clearInterval(twTimer); twTimer = null; }
  }
  function typewriter(node, caret, full, onDone) {
    stopTypewriter();
    var step = Math.max(2, Math.ceil(full.length / 60));
    var pos = 0;
    twTimer = setInterval(function () {
      pos = Math.min(pos + step, full.length);
      node.textContent = full.slice(0, pos);
      if (pos >= full.length) {
        stopTypewriter();
        if (caret.parentNode) caret.remove();
        if (onDone) onDone();
      }
    }, 30);
  }

  // ===== 追问区：胶囊一键追问 + 输入框 + 打字机回答（引擎 localAnswer 确定性兜底） =====
  function buildAskCard(structured, chips) {
    var card = el('div', 'card ask-card');
    add(card, el('div', 'card-title', '基于这份结果追问'));
    var hints = el('div', 'ask-hints');
    add(card, hints);

    var row = el('div', 'ask-input-row');
    var input = el('input', 'ask-input');
    input.placeholder = '追问这份结果，例如：风险点有哪些';
    var send = el('div', 'btn ask-send', '提问');
    add(row, input, send);
    add(card, row);

    var convo = el('div');
    add(card, convo);

    var pending = null;
    function ask(q) {
      q = String(q || '').trim();
      if (!q || !structured) return;
      // 上一发还在打字就被打断：直接落全文，不留半截答案
      if (pending) {
        stopTypewriter();
        pending.textNode.textContent = pending.full;
        if (pending.caret && pending.caret.parentNode) pending.caret.remove();
        pending = null;
      }
      add(convo, qaBubble('user', q).node);
      input.value = '';
      var answer = engine.localAnswer(q, { structured: structured }) || '未能获得回答，请稍后重试。';
      var ai = qaBubble('ai', '');
      add(convo, ai.node);
      pending = { textNode: ai.textNode, caret: ai.caret, full: answer };
      typewriter(ai.textNode, ai.caret, answer, function () { pending = null; });
    }

    chips.forEach(function (c) {
      var chip = el('span', 'ask-hint' + (c.key ? ' ask-hint-key' : ''), c.label || c.q);
      chip.addEventListener('click', function () { ask(c.q); });
      add(hints, chip);
    });

    send.addEventListener('click', function () { ask(input.value); });
    input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') ask(input.value); });
    return card;
  }

  function qaBubble(role, text) {
    var box = el('div', 'qa ' + (role === 'user' ? 'qa-user' : 'qa-ai'));
    var textNode = el('span', 'qa-text', text);
    add(box, el('span', 'qa-role', role === 'user' ? '我' : 'AI'), textNode);
    var caret = null;
    if (role === 'ai' && text === '') {
      caret = el('span', 'qa-caret', '▍');
      add(box, caret);
    }
    return { node: box, textNode: textNode, caret: caret };
  }

  // ===== 步骤回放条：复刻 step-trace 的「骨架先行」 =====
  function buildTrace(titles, onDone) {
    var box = el('div', 'trace');
    var pct = el('span', null, '0%');
    var label = el('span', null, '离线内核 · 真实计算');
    var head = el('div', 'trace-head');
    add(head, label, pct);
    var bar = el('div', 'trace-bar');
    var fill = el('i');
    fill.style.width = '0%';
    add(bar, fill);
    add(box, head, bar);

    var stepEls = titles.map(function (t) {
      var s = el('div', 'trace-step');
      add(s, el('span', 'trace-dot'), el('span', null, t));
      add(box, s);
      return s;
    });

    var i = 0;
    function next() {
      if (i > 0) {
        stepEls[i - 1].classList.remove('doing');
        stepEls[i - 1].classList.add('done');
      }
      if (i >= titles.length) {
        pct.textContent = '100%';
        fill.style.width = '100%';
        onDone();
        return;
      }
      stepEls[i].classList.add('doing');
      i++;
      var p = Math.round((i / titles.length) * 100);
      pct.textContent = p + '%';
      fill.style.width = p + '%';
      setTimeout(next, 90);
    }
    setTimeout(next, 30);
    return box;
  }

  // ===== 页面：首页（秒开证据 + 场景入口 + 最近记录 + 统计） =====
  function pageHome(root, bootMs) {
    var all = cache.rank();
    var hero = el('div', 'hero content-enter');
    var metrics = el('div', 'hero-metrics');
    [[bootMs, '启动准备 ms'], [firstPaintMs || Math.round(performance.now() - BOOT_T0), '首屏渲染 ms'], [all.length, '缓存命中条']].forEach(function (m) {
      var cell = el('div', 'metric');
      add(cell, el('span', 'metric-value mono', String(m[0])), el('span', 'metric-label', m[1]));
      add(metrics, cell);
    });
    var heroTags = el('div', 'hero-tags');
    add(heroTags, el('span', 'tag tag-offline', '离线内核运行中'), el('span', 'tag ' + (all.length ? 'tag-ok' : 'tag-offline'), all.length ? '本地缓存已加载' : '暂无本地缓存'));
    add(hero,
      el('div', 'hero-title', '秒开 AI 智能体'),
      el('div', 'hero-sub', '首屏不等网络，缓存先出内容，AI 再增量补齐'),
      metrics, heroTags);
    add(root, hero);

    var scenes = [
      { title: '一页纸快读', desc: '论文/财报/长文 → 结论 + 指标徽章 + 风险红线卡 + 竞争格局', go: '去速读 ›', tab: 'quickread' },
      { title: '日程断舍离', desc: '杂乱待办 → Top3 + 可延后 + 删除建议 + 时间块', go: '去整理 ›', tab: 'triage' }
    ];
    scenes.forEach(function (sc) {
      var card = el('div', 'card scene-card');
      var body = el('div', 'scene-body');
      add(body, el('div', 'scene-title', sc.title), el('div', 'scene-desc muted', sc.desc));
      var row = el('div', 'row-between');
      add(row, body, el('div', 'scene-go', sc.go));
      add(card, row);
      card.addEventListener('click', function () { switchTab(sc.tab); });
      add(root, card);
    });

    var recCard = el('div', 'card');
    var recHead = el('div', 'row-between');
    add(recHead, el('span', 'card-title', '最近记录'));
    if (all.length) {
      var clear = el('span', 'muted', '清空');
      clear.style.cssText = 'font-size:12px;text-decoration:underline;cursor:pointer;';
      clear.addEventListener('click', function () {
        cache.clear();
        inMemory = { quickread: null, triage: null };
        toast('缓存已清空');
        render();
      });
      add(recHead, clear);
    }
    add(recCard, recHead);

    if (!all.length) {
      var empty = el('div', 'empty-box');
      add(empty, el('span', 'empty-icon', '◎'), el('div', null, '还没有记录'), el('div', null, '进入任一场景，粘贴内容即可生成第一份结果'));
      var go = el('div', 'btn');
      go.style.cssText = 'display:inline-block;margin-top:10px;padding:8px 18px;';
      go.textContent = '开始一页纸快读';
      go.addEventListener('click', function () { switchTab('quickread'); });
      add(empty, go);
      add(recCard, empty);
    } else {
      all.slice(0, 8).forEach(function (r, idx) {
        var item = el('div', 'recent-item content-enter');
        var row = el('div', 'row-between');
        add(row, el('span', 'recent-title', r.title), el('span', 'tag', r.scene === 'triage' ? '断舍离' : '一页纸'));
        add(item, row, el('div', 'recent-summary muted', r.summary || r.scene));
        item.addEventListener('click', function () {
          navigateTo(r.scene === 'triage' ? 'today' : 'detail', { id: r.id });
        });
        add(recCard, item);
        if (idx < Math.min(all.length, 8) - 1) add(recCard, el('div', 'divider'));
      });
    }
    add(root, recCard);

    // 运行统计（本地）：与小程序首页同口径，数据全部来自缓存真实记录
    var withMs = all.filter(function (r) { return r.meta && r.meta.elapsedMs; });
    var avgMs = withMs.length ? Math.round(withMs.reduce(function (s, r) { return s + r.meta.elapsedMs; }, 0) / withMs.length) : 0;
    var stat = el('div', 'card');
    add(stat, el('div', 'card-title', '运行统计（本地）'));
    [['累计分析', all.length + ' 次'], ['平均耗时', avgMs ? avgMs + ' ms' : '—'], ['离线内核', withMs.length + ' 次（本模拟器）']].forEach(function (p) {
      var row = el('div', 'stat-row');
      add(row, el('span', 'muted', p[0]), el('span', 'mono', p[1]));
      add(stat, row);
    });
    add(root, stat);
  }

  // ===== 页面：一页纸快读（输入 + 步骤 + 结果） =====
  function pageQuickread(root) {
    var card = el('div', 'card');
    var head = el('div', 'row-between');
    var counter = el('span', 'muted mono', '0/8000');
    add(head, el('span', 'card-title', '粘贴论文 / 财报 / 长文'), counter);
    var ta = el('textarea', 'ta');
    ta.placeholder = '把长文粘贴到这里。秒开策略：结果先生成结构化骨架，再流式补齐内容。';
    ta.maxLength = 8000;
    ta.addEventListener('input', function () { counter.textContent = ta.value.length + '/8000'; });
    var actions = el('div', 'action-row');
    var bSample = el('div', 'btn btn-ghost action-sample', '填入示例');
    var bClear = el('div', 'btn btn-ghost action-clear', '清空');
    var bRun = el('div', 'btn', '生成一页纸');
    add(actions, bSample, bClear, bRun);
    add(card, head, ta, actions);
    add(root, card);

    var out = el('div');
    add(root, out);

    if (inMemory.quickread) {
      renderQrResult(inMemory.quickread);
    }

    bSample.addEventListener('click', function () {
      ta.value = SAMPLE_QR;
      counter.textContent = SAMPLE_QR.length + '/8000';
    });
    bClear.addEventListener('click', function () {
      ta.value = '';
      counter.textContent = '0/8000';
      inMemory.quickread = null;
      out.innerHTML = '';
    });
    bRun.addEventListener('click', function () {
      var text = decode.normalizeInput(ta.value);
      if (!text) { toast('请先粘贴内容'); return; }
      out.innerHTML = '';
      bRun.classList.add('btn-danger');
      bRun.textContent = '分析中';
      add(out, buildTrace(
        ['解析文本 · 归一化', 'TF-IDF 摘要打分', '关键数据抽取', '风险红线穿透', '竞争格局识别', '一页纸渲染'],
        function () {
          var t0 = performance.now();
          var result = engine.analyzeDocument(text, { maxSentences: 3 });
          var elapsed = Math.max(1, Math.round(performance.now() - t0));
          bRun.classList.remove('btn-danger');
          bRun.textContent = '生成一页纸';
          renderQrResult({ result: result, text: text, elapsed: elapsed });
        }
      ));
    });

    function renderQrResult(run) {
      var s = run.result;
      inMemory.quickread = run;
      persist('qr', {
        scene: 'quickread',
        title: String(s.conclusion || '一页纸快读').slice(0, 24),
        summary: (s.keyData || []).map(function (d) { return d.value; }).slice(0, 3).join(' · '),
        raw: run.text.slice(0, 4000),
        score: (s.keyData || []).length * 10 + (s.risks || []).length * 6,
        tags: ['一页纸', '离线'],
        meta: { offline: true, structured: s.structured, elapsedMs: run.elapsed }
      });
      var wrap = el('div');
      var metaRow = el('div', 'row-between');
      metaRow.style.cssText = 'padding:0 6px 6px;';
      add(metaRow,
        el('span', 'muted', '耗时 ' + run.elapsed + ' ms'),
        el('span', 'tag tag-offline', '离线分析'));
      var actions = el('div', 'result-actions');
      var bHistory = el('div', 'btn btn-ghost', '回首页看缓存');
      var bDetail = el('div', 'btn', '查看详情与追问');
      add(actions, bHistory, bDetail);
      add(wrap, metaRow, renderResearch(s.structured), actions);
      out.appendChild(wrap);
      bHistory.addEventListener('click', function () { switchTab('home'); });
      bDetail.addEventListener('click', function () {
        navigateTo('detail', { live: true });
      });
      wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      renderTabbar();
    }
  }

  function persist(prefix, rec) {
    try {
      cache.put(Object.assign({ id: prefix + '_' + Date.now(), ts: Date.now(), hit: 0 }, rec));
    } catch (e) {}
  }

  // ===== 页面：日程断舍离 =====
  function pageTriage(root) {
    var card = el('div', 'card');
    var head = el('div', 'row-between');
    var counter = el('span', 'muted mono', '0/8000');
    add(head, el('span', 'card-title', '粘贴今日待办清单'), counter);
    var ta = el('textarea', 'ta');
    ta.placeholder = '一行一条待办。秒开策略：本地内核即时评分，Top3 + 删除建议 + 时间块。';
    ta.maxLength = 8000;
    ta.addEventListener('input', function () { counter.textContent = ta.value.length + '/8000'; });
    var actions = el('div', 'action-row');
    var bSample = el('div', 'btn btn-ghost action-sample', '填入示例');
    var bClear = el('div', 'btn btn-ghost action-clear', '清空');
    var bRun = el('div', 'btn', '断舍离');
    add(actions, bSample, bClear, bRun);
    add(card, head, ta, actions);
    add(root, card);

    var out = el('div');
    add(root, out);

    if (inMemory.triage) renderTrResult(inMemory.triage);

    bSample.addEventListener('click', function () {
      ta.value = SAMPLE_TR;
      counter.textContent = SAMPLE_TR.length + '/8000';
    });
    bClear.addEventListener('click', function () {
      ta.value = '';
      counter.textContent = '0/8000';
      inMemory.triage = null;
      out.innerHTML = '';
    });
    bRun.addEventListener('click', function () {
      var text = decode.normalizeInput(ta.value);
      if (!text) { toast('请先粘贴待办'); return; }
      out.innerHTML = '';
      add(out, buildTrace(
        ['按行拆分待办', '紧急度 / 影响面评分', '噪声识别与删除建议', 'Top3 排序', '时间块编排'],
        function () {
          var t0 = performance.now();
          var result = engine.analyzeSchedule(text, { now: Date.now() });
          var elapsed = Math.max(1, Math.round(performance.now() - t0));
          renderTrResult({ result: result, text: text, elapsed: elapsed });
        }
      ));
    });

    function renderTrResult(run) {
      var s = run.result;
      inMemory.triage = run;
      persist('tr', {
        scene: 'triage',
        title: String((s.structured.today[0] && s.structured.today[0].text) || '今日安排').slice(0, 24),
        summary: s.summary + ' · 删除 ' + s.deletions.length + ' 项',
        raw: run.text.slice(0, 4000),
        score: s.structured.today.length * 10 + s.deletions.length * 6,
        tags: ['断舍离', '离线'],
        meta: { offline: true, structured: s.structured, elapsedMs: run.elapsed }
      });
      var wrap = el('div');
      var metaRow = el('div', 'row-between');
      metaRow.style.cssText = 'padding:0 6px 6px;';
      add(metaRow, el('span', 'muted', '耗时 ' + run.elapsed + ' ms'), el('span', 'tag tag-offline', '离线分析'));
      var actions = el('div', 'result-actions');
      var bToday = el('div', 'btn', '查看今日安排与追问');
      add(actions, bToday);
      add(wrap, metaRow, renderTriage(s.structured), actions);
      out.appendChild(wrap);
      bToday.addEventListener('click', function () { navigateTo('today', { live: true }); });
      renderTabbar();
    }
  }

  // ===== 子页：快读详情（回放 + 追问） =====
  function findRecord(scene, id) {
    var rec = null;
    if (id) rec = cache.get(id);
    if (!rec) {
      var top = cache.rank().filter(function (r) { return r.scene === scene; });
      if (top.length) rec = top[0];
    }
    return rec;
  }

  function pageDetail(root, params) {
    var live = params.live && inMemory.quickread;
    var structured = null;
    var title = '暂无记录';
    if (live) {
      structured = inMemory.quickread.result.structured;
      title = inMemory.quickread.result.conclusion;
    } else {
      var rec = findRecord('quickread', params.id);
      if (rec && rec.meta) {
        structured = rec.meta.structured;
        title = rec.title;
      }
    }

    if (!structured) {
      var empty = el('div', 'card empty-box');
      add(empty, el('span', 'empty-icon', '◌'), el('div', null, '没有找到这条记录'), el('div', null, '记录可能已被清空，回到快读页重新生成即可'));
      var go = el('div', 'btn');
      go.style.cssText = 'display:inline-block;margin-top:10px;padding:8px 18px;';
      go.textContent = '去生成';
      go.addEventListener('click', function () { switchTab('quickread'); });
      add(empty, go);
      add(root, empty);
      return;
    }

    var head = el('div', 'head-row row-between');
    add(head, el('span', 'head-title', String(title).slice(0, 30)), el('span', 'tag tag-offline', '离线分析'));
    add(root, head);
    add(root, renderResearch(structured));
    add(root, buildAskCard(structured, [
      { q: '分析该标的核心护城河与三大估值下行风险', key: true },
      { q: '有哪些风险点？' },
      { q: '行业竞争格局如何？', label: '行业竞争格局' },
      { q: '关键数据是多少？' },
      { q: '这是什么文体？', label: '文体识别' },
      { q: '结论是什么？' }
    ]));
  }

  // ===== 子页：今日安排（概览 + 追问） =====
  function pageToday(root, params) {
    var live = params.live && inMemory.triage;
    var structured = null;
    var title = '暂无安排';
    if (live) {
      structured = inMemory.triage.result.structured;
      title = '今日断舍离安排';
    } else {
      var rec = findRecord('triage', params.id);
      if (rec && rec.meta) {
        structured = rec.meta.structured;
        title = rec.title;
      }
    }

    if (!structured) {
      var empty = el('div', 'card empty-box');
      add(empty, el('span', 'empty-icon', '◌'), el('div', null, '还没有今日安排'), el('div', null, '回到断舍离页粘贴待办，即可生成今日安排'));
      var go = el('div', 'btn');
      go.style.cssText = 'display:inline-block;margin-top:10px;padding:8px 18px;';
      go.textContent = '去整理';
      go.addEventListener('click', function () { switchTab('triage'); });
      add(empty, go);
      add(root, empty);
      return;
    }

    var hero = el('div', 'today-hero content-enter');
    var metrics = el('div', 'today-hero-metrics');
    [[structured.today.length, '今日必做'], [structured.defer.length, '可延后'], [structured.deletions.length, '建议删除']].forEach(function (m) {
      var cell = el('div', 'thm');
      add(cell, el('span', 'thm-value mono', String(m[0])), el('span', 'thm-label', m[1]));
      add(metrics, cell);
    });
    var tags = el('div', 'today-hero-tags');
    add(tags, el('span', 'tag', '离线分析'));
    add(hero, el('div', 'today-hero-title', title), metrics, tags);
    add(root, hero);

    add(root, renderTriage(structured));
    add(root, buildAskCard(structured, [
      { q: '建议删除哪些？', key: true },
      { q: '今日必做是什么？' },
      { q: '时间块怎么排？' }
    ]));
  }

  // ===== 主渲染 =====
  var bootMs = 0;
  var firstPaintMs = 0;

  function render(isBack) {
    var route = currentRoute();
    stopTypewriter();
    viewport.innerHTML = '';
    var page = el('div', 'page-root ' + (isBack ? 'page-back' : 'page'));
    add(viewport, page);

    if (route.name === 'home') pageHome(page, bootMs);
    else if (route.name === 'quickread') pageQuickread(page);
    else if (route.name === 'triage') pageTriage(page);
    else if (route.name === 'detail') pageDetail(page, route.params);
    else if (route.name === 'today') pageToday(page, route.params);

    navTitle.textContent = NAV_TITLES[route.name] || '秒开 AI';
    navBack.classList.toggle('on', routeStack.length > 1);
    navBack.style.visibility = routeStack.length > 1 ? 'visible' : 'hidden';
    renderTabbar();
    updateSideStats();
    viewport.scrollTop = 0;
  }

  navBack.addEventListener('click', navigateBack);

  function updateSideStats() {
    var st = cache.stats();
    document.getElementById('side-stats').textContent =
      'localStorage 记录 ' + st.count + ' 条 · 约 ' + Math.round(st.bytes / 1024) + ' KB';
  }

  document.getElementById('btn-reset').addEventListener('click', function () {
    cache.clear();
    inMemory = { quickread: null, triage: null };
    toast('模拟缓存已清空');
    render();
  });

  // ===== 状态栏时钟：模拟真机 =====
  function tickClock() {
    var d = new Date();
    var h = d.getHours(), m = d.getMinutes();
    document.getElementById('sb-time').textContent = h + ':' + (m < 10 ? '0' : '') + m;
  }
  tickClock();
  setInterval(tickClock, 30000);

  // 首帧：先测「启动准备」，渲染完成后再回填「首屏渲染」，与小程序秒开口径一致
  requestAnimationFrame(function () {
    bootMs = Math.max(1, Math.round(performance.now() - BOOT_T0));
    render();
    firstPaintMs = Math.max(bootMs, Math.round(performance.now() - BOOT_T0));
  });
})();
