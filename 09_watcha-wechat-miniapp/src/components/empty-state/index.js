// empty-state：统一空态 / 首屏骨架占位。
// 两种模式：skeleton=true 时渲染灰块骨架（首屏 0 网络时立即有内容）；
// 否则渲染图标 + 标题 + 描述 + 可选按钮。

Component({
  properties: {
    icon: {
      type: String,
      value: '○'
    },
    title: {
      type: String,
      value: '暂无内容'
    },
    desc: {
      type: String,
      value: ''
    },
    actionText: {
      type: String,
      value: ''
    },
    skeleton: {
      type: Boolean,
      value: false
    },
    // 骨架灰块行数
    rows: {
      type: Number,
      value: 3
    }
  },

  data: {
    placeholders: []
  },

  observers: {
    rows: function (rows) {
      const n = rows > 0 ? rows : 3;
      const list = [];
      for (let i = 0; i < n; i++) list.push(i);
      this.setData({ placeholders: list });
    }
  },

  methods: {
    onAction() {
      this.triggerEvent('action');
    }
  }
});
