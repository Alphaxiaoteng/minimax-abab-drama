// markdown-card：把结构化一页纸渲染成 4 个区块。
// 输入 structured（quickread: conclusion/keyData/risks/evidence；triage: today/defer/deletions/timeBlocks）。
// 纯展示组件，不做任何数据加工，避免把渲染逻辑散到组件里。

const SECTION_TITLES = {
  quickread: {
    conclusion: '一句话结论',
    keyData: '关键数据',
    risks: '风险点',
    evidence: '原文引用依据'
  },
  triage: {
    today: '今日必做',
    defer: '可延后',
    deletions: '建议删除',
    timeBlocks: '时间块'
  }
};

Component({
  properties: {
    scene: {
      type: String,
      value: 'quickread'
    },
    structured: {
      type: Object,
      value: null
    },
    // 是否处于离线降级结果，页面上要如实标注
    offline: {
      type: Boolean,
      value: false
    }
  },

  data: {
    sections: []
  },

  observers: {
    'structured, scene': function (structured, scene) {
      this.setData({ sections: this.buildSections(scene, structured) });
    }
  },

  methods: {
    // 把 structured 压成统一区块数组，wxml 只负责遍历，保持模板极简。
    buildSections(scene, structured) {
      if (!structured) return [];
      const titles = SECTION_TITLES[scene] || SECTION_TITLES.quickread;
      const out = [];

      if (scene === 'triage') {
        out.push({
          key: 'today',
          title: titles.today,
          kind: 'ordered',
          items: this.toTextList(structured.today, 'text')
        });
        out.push({
          key: 'defer',
          title: titles.defer,
          kind: 'plain',
          items: this.toTextList(structured.defer)
        });
        out.push({
          key: 'deletions',
          title: titles.deletions,
          kind: 'reason',
          items: (structured.deletions || []).map(function (d) {
            return { text: d.item || '', reason: d.reason || '' };
          }).filter(function (d) { return !!d.text; })
        });
        out.push({
          key: 'timeBlocks',
          title: titles.timeBlocks,
          kind: 'block',
          items: (structured.timeBlocks || []).map(function (b) {
            return { text: b.start + ' - ' + b.end, label: b.label || '', type: b.type || 'must' };
          })
        });
      } else {
        out.push({
          key: 'conclusion',
          title: titles.conclusion,
          kind: 'plain',
          items: structured.conclusion ? [{ text: structured.conclusion }] : []
        });
        out.push({
          key: 'keyData',
          title: titles.keyData,
          kind: 'kv',
          items: (structured.keyData || []).map(function (d) {
            return { text: d.value || '', label: d.label || '' };
          })
        });
        out.push({
          key: 'risks',
          title: titles.risks,
          kind: 'plain',
          items: (structured.risks || []).map(function (r) {
            return { text: r.text || '' };
          })
        });
        out.push({
          key: 'evidence',
          title: titles.evidence,
          kind: 'quote',
          items: (structured.evidence || []).map(function (e) {
            return { text: e.text || '' };
          })
        });
      }

      // 过滤掉没有内容的区块，避免页面出现空标题
      return out.filter(function (s) { return s.items.length > 0; });
    },

    toTextList(list, field) {
      const src = list || [];
      return src.map(function (it) {
        if (typeof it === 'string') return { text: it };
        return { text: field && it && it[field] ? it[field] : String(it) };
      }).filter(function (it) { return !!it.text; });
    },

    // 长按区块触发复制，方便评委把结果粘出去验证真实性
    onCopy(e) {
      const text = e.currentTarget.dataset.text;
      if (!text) return;
      wx.setClipboardData({
        data: String(text),
        success() {
          wx.showToast({ title: '已复制', icon: 'success' });
        }
      });
    }
  }
});
