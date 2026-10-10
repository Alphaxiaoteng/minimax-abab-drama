# 雾客松 2027（WAKEATHON）重庆跨年 AI 黑客松 - 研发工程工作区

- **赛事 ID**：`hackertrip-d2568be6-0841-4994-910b-ba5b6b1ed532`
- **当前状态**：`已报名待提交`
- **报名截止**：`2027-01-10`
- **奖金激励**：`总奖池超 20 万元：冠军 8 万元现金+奖杯、亚军 4 万元、季军 2 万元；`
- **官方链接**：[https://hackertrip.space/hackathon/d2568be6-0841-4994-910b-ba5b6b1ed532](https://hackertrip.space/hackathon/d2568be6-0841-4994-910b-ba5b6b1ed532)

## 🎯 交付目标
- [x] 完成架构设计与需求拆解
- [x] 搭建 `src/` 核心功能代码（v0.2 综合原型 + 现场评测架构已就绪）
- [x] 编写自动化评测脚本（12 用例 × 两阵营，客观五维评分）
- [ ] 录制演示视频 (2-5 分钟清晰操作)
- [ ] 提交材料归档至 `docs/` 并完成官方提审

## 🧱 原型「雾醒山城」（src/，v0.2）

技术栈：Vite + React 18 + TypeScript(strict) + Three.js（UnrealBloom 辉光 + 自定义撕裂 Pass）；另有一条零 WebGL 依赖的 DOM+Canvas 后备阵营，同签名可互换。

核心思路：把「演出」本身变成数据。全部 11 类视觉效果统一为类型化命令 `SceneEffect`，12 幕跨年大秀写成冻结的分镜脚本，视觉实现退化为可替换的**渲染阵营**——评测引擎以固定步长重放同一命令队列并逐帧采样，得到与渲染细节无关的能量曲线，因此「观感」可量化、可回归。

```text
src/src/
├── core/
│   ├── contract.ts      # 唯一契约源：SceneEffect(11 动作) / SceneRenderer / HarnessDriver / ScenePlan
│   ├── events.ts        # 类型化事件总线（ui:intent / agent:command / show:cue / wake:moment …）
│   └── timeline.ts      # 12 幕分镜脚本 SHOW_PLANS + buildTimeline（脚本 → t=0 起算的命令队列）
├── ai/                  # 意图 → 命令 → 台词：parseIntent 纯函数 + ShowDirector + 可插拔 LLM 适配器
│   ├── intents.ts       #   中英关键词/复合意图/强度词解析，确定性台词散列，可离线评测
│   ├── show.ts          #   ShowDirector：按时间轴推进 12 幕，setTimeout 递进，stop/jumpTo/setSpeed
│   ├── mock-agent.ts    #   FogSpriteAgent（规则型，演示与评测同源）
│   └── llm-agent.ts     #   LlmAgent（OpenAI 兼容，JSON 模式，失败自动降级，不抛错）
├── visual/              # Three.js 阵营：SkyEngine 实现 SceneRenderer，11 动作全部可见
│   ├── sky-engine.ts    #   统一 advance(dt) 状态积分器；sample() 只由积分决定（可复现）
│   ├── city/fog/fireworks/lasers/drones/mascot/spotlights/confetti/glitch.ts
│   └── driver.ts        #   createThreeDriver → HarnessDriver（评测用）
├── css/                 # CSS/Canvas 阵营：CssRenderer，同 SceneEffect 语义，固定种子 PRNG
│   ├── renderer.ts      #   90+ DOM 楼体 / Canvas 加色粒子 / 「2027」点阵字形无人机
│   ├── scene.css        #   独立 cssc- 前缀样式
│   └── driver.ts        #   createCssDriver → HarnessDriver
├── hud/                 # React 指挥中心：倒计时+进度环 / 分镜轨道 / 事件流 / 控制台 / 引擎切换 / 调试台
└── eval/                # 现场评测架构（详见 docs/EVALUATION.md）
    ├── metrics.ts       #   覆盖率 / 耦合度(Jaccard) / 节奏谱 / 逐动作峰值
    ├── harness.ts       #   固定步长重放 + 意图真实链路 + 确定度(两次重放比对)
    ├── judge.ts         #   纯函数五维加权评分 + 一票否决封顶
    ├── scenarios.json   #   12 用例（show / intent / engine / robust）
    ├── bridge.ts        #   页面内 window.__wakeEval 注入（?eval=1 触发）
    └── cli.ts           #   Playwright 驱动：JSON + HTML + docs/REPORT.md
```

数据流：`HUD 意图 → bus(ui:intent) → AgentRuntime → parseIntent/ShowDirector → bus(agent:utterance + agent:command) → 渲染阵营实时积分 → sample()`

本地运行：`cd src && npm install && npx playwright install chromium && npm run dev`
构建：`npm run build`（tsc --noEmit 全绿 + vite 打包）
评测：`npm run eval`（两阵营 × 12 用例，输出 `.verify/eval-report.{json,html}` 与 `docs/REPORT.md`）

## 📝 进度日志
- 2026-10-10：v0.1 事件总线驱动的「意图 → Agent → 视觉」闭环打通，Mock 雾灵可替换为真实 LLM 适配器。
- 2026-10-10：v0.2 升级为 12 幕自动化大秀 + 双渲染阵营（Three.js / CSS 同签名互换）+ 现场评测架构。意图解析、ShowDirector、LLM 适配器、指挥中心 HUD、评测五维评分全部就位；`tsc`/`vite build` 全绿，Playwright 评测跑通（两阵营确定度 1.0、控制台 0 错误）。

> 详细比赛规则、打分指标与避开红海的破局打法，请参阅同目录下的 [RULES.md](file:///Users/albert/Documents/project/apps/bisai/18_wakeathon-chongqing-2027/RULES.md)。
