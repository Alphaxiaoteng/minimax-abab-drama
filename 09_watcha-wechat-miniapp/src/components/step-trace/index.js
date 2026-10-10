// step-trace：骨架步骤可视化。
// 展示 agent 首帧下发的骨架（解析文本 → 结论 → 数据 → 风险 → 引用），随流式推进点亮。
// 这是「秒开感」的关键组件：即使模型还没返回任何文本，用户也立刻看到结构在动。

Component({
  properties: {
    // 骨架步骤：[{ id, name, state: 'pending'|'running'|'done', text }]
    steps: {
      type: Array,
      value: []
    },
    // 0-100
    progress: {
      type: Number,
      value: 0
    },
    // 是否展开每一步的产出文本
    expandable: {
      type: Boolean,
      value: true
    }
  },

  data: {
    expanded: false
  },

  methods: {
    // 收起/展开步骤明细，默认收起以保持首屏干净
    toggleExpand() {
      this.setData({ expanded: !this.data.expanded });
    }
  }
});
