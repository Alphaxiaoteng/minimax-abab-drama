# 雾醒山城 · 评测架构

> 目标：把「视觉冲击力」「智能体编排」「稳定性」这些通常只能靠人眼拍板的判断，拆成**可复现、可对比、可回归**的客观读数，让每一次改版都能秒级回答「这次改动让作品更好还是更差」。

## 一、为什么要自建评测，而不是靠人眼

黑客松最常见的失分点是：演示当天才知道动画崩了 / 显卡不支持 WebGL / 改一处特效把另一处节奏打乱。本工程的应对方式是**把演出本身变成数据**：

- 全部 11 类视觉效果统一为一个类型化命令集 `SceneEffect`（`src/core/contract.ts`）。
- 12 幕演出写成**分镜脚本**（`src/core/timeline.ts` 的 `SHOW_PLANS`），由时间轴翻译成 `t=0` 起算的命令队列。
- 视觉实现退化为可互换的**渲染阵营**：`three`（Three.js/WebGL）与 `css`（DOM+Canvas 零依赖后备），两者实现同一接口 `SceneRenderer` + `HarnessDriver`。
- 评测引擎以固定步长 `dt` 重放命令队列并逐帧采样引擎状态 `sample()`，得到与渲染细节无关的能量曲线。

因此「Three.js 版和 CSS 版哪个更稳」「这次调参让零点更炸了吗」都能用同一份用例直接量化。

## 二、五维客观评分（`src/eval/judge.ts`）

| 维度 | 权重 | 客观口径 |
| --- | --: | --- |
| 视觉覆盖率 | 0.25 | 用例预期动作真正亮起的比例；再与「11 类动作的峰值覆盖」按 65:35 加权 |
| 编排耦合度 | 0.20 | 相邻帧活跃动作集合的 Jaccard 均值 —— 高=多路并发编排，低=单点轮播 |
| 节奏曲线 | 0.20 | 全场峰值出现的相对位置（越靠后越好）+ 起伏度（过高过低都减分）+ 首幕铺垫 |
| 确定度 | 0.15 | 同一 `dt` 序列重放两遍，逐帧读数最大差值取反 |
| 鲁棒性 | 0.20 | 乱码/空/超长意图下无异常、无 NaN 的帧占比，与断言通过率按 70:30 加权 |

**封顶规则**（对应评委视角的一票否决）：

1. 引擎抛异常或出现 NaN → 总分 ≤ 59
2. 重放读数不一致（确定度 < 0.999）→ 总分 ≤ 74
3. 覆盖率 < 0.50 → 总分 ≤ 69
4. 任一条断言未通过 → 总分 ≤ 79（不可进入优秀区）

评分为**纯函数**：`(MetricReport, Scenario) → JudgeResult`，无 IO、无时钟、无随机，可离线复算与回归比对。

## 三、用例集（`src/eval/scenarios.json`，12 条 / 4 类）

| 类别 | 用例 | 考什么 |
| --- | --- | --- |
| `show` | `show-full-arc` | 12 幕全覆盖，11 类动作全亮 |
| `show` | `opening-lamplight` | 开场只许灯火：**否定断言**不得提前放烟花 / 不得出现日出色温 |
| `show` | `fog-river` | 雾必须持续在场（均值下限），且不得遮死霓虹 |
| `show` | `zero-peak` | 零点三路并发（烟花 ≥0.75 / 冲击帧 / 激光） |
| `show` | `dawn-shift` | 色温迁移达标 + 黎明阶段烟花退场 |
| `show` | `finale` | 谢幕彩纸 + 尾焰 + 图腾 |
| `intent` | `intent-fog-poetic` / `intent-fireworks-hype` / `intent-energy-cluster` | 自然语言 → 命令映射；复合意图（激光+无人机+全部拉满） |
| `engine` | `engine-low-tier` | 低配降级后峰值能量不得丢失 |
| `engine` | `determinism-check` | 两次重放逐帧一致 |
| `robust` | `robust-garbage` | 空串、符号、超长中文串不得让引擎崩或输出 NaN |

断言支持 `minPeak`（峰值下限）、`minMean`（均值下限，用于「持续在场」而非「闪一下」）、`notAction`（否定断言）与 `window`（时间窗限定）。

## 四、运行链路

```
npx tsx src/eval/cli.ts
   │
   ├─ 启动 vite（:5199） + Playwright chromium（1600x900）
   ├─ 打开 http://localhost:5199/?eval=1   → main.tsx 条件注入 window.__wakeEval
   ├─ 页面内 bridge.ts：对 three / css 两阵营各跑全部用例
   │     runScenario → framesFor（固定 dt 重放 + apply 命令 + sample 采样）
   │     → MetricReport（覆盖率/耦合/确定度/鲁棒/节奏谱/逐动作峰值）
   │     → judgeReport → 五维评分 + 封顶
   └─ 落盘：
        .verify/eval-report.json    机器可读明细（回归比对基线）
        .verify/eval-report.html    可投屏/截图的可视化报告
        docs/REPORT.md              提交材料用结论
```

> 为什么必须用真浏览器：css 阵营要在真实布局下测 DOM 尺寸，three 阵营要真实 WebGL 上下文。jsdom 下两者都是空壳，任何帧率/观感结论都不可信。

## 五、复现与回归

```bash
cd src
npm install                 # 首次
npx playwright install chromium

npm run eval                # 全量（three + css）
npm run eval -- --only zero-peak            # 单用例
npm run eval:peek -- --only show-full-arc   # 带界面观察
npm run verify              # typecheck + build + eval 全链路
```

回归比对：把 `.verify/eval-report.json` 提交进仓库，改动后重跑并 diff `summary.mean` 与各用例 `total`；某用例掉分即定位到对应断言。

## 六、设计约束（写给后续维护者）

1. `src/core/contract.ts` 是**唯一契约源**；改动作集合必须同步更新 `ACTION_NAMES`、`scenarios.json` 与两阵营实现。
2. 引擎的 `sample()` **禁止**依赖 `Math.random()` 或真实时钟：时间只来自 `advance(dt)`，随机只能来自构造期的固定种子 PRNG。否则确定度维度必然挂。
3. 评测层不静态 import 具体阵营：driver 工厂由 `bridge.ts` 注入，保证 `eval/*` 可被离线复用（纯指标与判分不需要浏览器）。
4. 新增视觉动作时：先加 `SceneEffect` 联合成员 → 两阵营各实现 → 加一条断言（至少 `minPeak`）→ 跑 `npm run eval` 确认只有新用例变动。
