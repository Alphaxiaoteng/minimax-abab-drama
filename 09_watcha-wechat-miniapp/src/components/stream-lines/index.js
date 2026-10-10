// stream-lines：流式增量文本渲染器。
// 职责单一：接收父页面节流后传入的文本，按行拆成可渐显的片，避免每次 setData 重建整棵树。
// 节流在页面侧做（见 pages/*/index.js），组件这里只负责把「已合并的文本」切成行。

Component({
  properties: {
    // 当前累计的完整文本（父页面已节流合并）
    text: {
      type: String,
      value: ''
    },
    // 是否仍在流式中：控制光标闪烁与底部留白
    streaming: {
      type: Boolean,
      value: false
    },
    // 最多渲染多少行，超出的折叠，防止长文本把页面撑爆
    maxLines: {
      type: Number,
      value: 40
    }
  },

  data: {
    lines: [],
    truncated: false
  },

  observers: {
    'text, maxLines': function (text, maxLines) {
      const raw = String(text || '');
      const all = raw.split('\n').map(function (l) { return l.trim(); }).filter(function (l) { return l.length > 0; });
      const cap = maxLines > 0 ? maxLines : 40;
      const shown = all.length > cap ? all.slice(all.length - cap) : all;
      this.setData({
        lines: shown,
        truncated: all.length > cap
      });
    }
  }
});
