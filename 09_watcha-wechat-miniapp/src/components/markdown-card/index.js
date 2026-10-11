// markdown-card：把结构化一页纸渲染成投研终端风格的多区块卡片。
// 输入 structured（quickread: conclusion/keyData/risks/riskCards/landscape/evidence；triage: today/defer/deletions/timeBlocks）。
// 纯展示组件，不做任何数据加工，避免把渲染逻辑散到页面里。

const SECTION_TITLES = {
  quickread: {
    conclusion: '一句话结论',
    keyData: '关键财务指标',
    risks: '风险点',
    riskCards: '风险红线警示',
    landscape: '行业竞争格局',
    evidence: '原文引用依据'
  },
  triage: {
    today: '今日必做',
    defer: '可延后',
    deletions: '建议删除',
    timeBlocks: '时间块'
  }
};

// keyData.kind → 徽章角标
const KIND_TAG = {
  percent: '比率',
  amount: '金额',
  year: '年份',
  multiple: '倍数',
  delta: '变动'
};

const SEVERITY_LABEL = { high: '红线', medium: '关注', low: '提示' };

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
    sections: [],
    formatLabel: ''
  },

  observers: {
    'structured, scene': function (structured, scene) {
      this.setData({
        sections: this.buildSections(scene, structured),
        formatLabel: structured && structured.format ? structured.format.label : ''
      });
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
        // 关键财务指标徽章：数值 + 标签 + 类型角标，网格排布对齐投研终端
        out.push({
          key: 'keyData',
          title: titles.keyData,
          kind: 'badge',
          items: (structured.keyData || []).map(function (d) {
            return {
              text: (d.value || '') + ' ' + (d.label || ''),
              value: d.value || '',
              label: d.label || '',
              tag: KIND_TAG[d.kind] || '指标'
            };
          })
        });
        // 风险穿透卡优先；引擎未给出 riskCards 时退回纯风险句
        const cards = structured.riskCards || [];
        if (cards.length) {
          out.push({
            key: 'riskCards',
            title: titles.riskCards,
            kind: 'riskcard',
            items: cards.map(function (c) {
              return {
                title: c.title || '风险信号',
                severity: c.severity || 'medium',
                severityLabel: SEVERITY_LABEL[c.severity] || '关注',
                detail: c.detail || '',
                keywords: (c.keywords || []).slice(0, 4)
              };
            })
          });
        } else {
          out.push({
            key: 'risks',
            title: titles.risks,
            kind: 'plain',
            items: (structured.risks || []).map(function (r) {
              return { text: r.text || '' };
            })
          });
        }
        // 行业竞争格局：仅当原文命中格局词时出现，绝不空造
        const land = structured.landscape || [];
        if (land.length) {
          out.push({
            key: 'landscape',
            title: titles.landscape,
            kind: 'landscape',
            items: land.map(function (l) {
              return { text: l.text || '', signals: l.signals || [] };
            })
          });
        }
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
