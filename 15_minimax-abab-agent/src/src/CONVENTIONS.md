# 共享架构规范（并行切片必须遵守）

所有切片在**同一进程、同一仓库**内并行开发。你只写自己负责的文件，禁止改动 `src/src/core/**` 下任何文件。

## 目录与所有权

```
src/src/
  core/       ← 已冻结（constants/errors/config/deterministic/types/contracts），只读
  personas/   ← SLICE B
  minimax/    ← SLICE C
  engine/     ← SLICE C
  eval/       ← SLICE D
  ui/         ← SLICE E
  server/     ← SLICE E
  cli/        ← SLICE E
  index.ts    ← 集成位（由集成负责人统一收敛，各切片不要写它）
```

## 硬性规则

1. **ESM + NodeNext 风格**：所有相对 import **必须带 `.js` 后缀**（`import { x } from './y.js'`），即使源文件是 `.ts`。这是 `verbatimModuleSyntax` + `moduleResolution: Bundler` 下的项目约定。
2. **只用类型导入写 `import type`**。运行时导出用普通 `import`。
3. **零新增依赖**：只用 Node 内置模块（`node:crypto`、`node:fs`、`node:http`、`node:path`、`node:url` 等）与浏览器内置 API。禁止 `fetch` 之外的第三方库；禁止安装 npm 包。
4. **确定性**：任何进入评测的路径都不得读取 `Date.now()`（除非通过注入的 `now()`）、`Math.random()`、真实网络。mock 路径必须同 seed 同输出。
5. **中文注释与中文 UI 文案**：这是面向 MiniMax 中文赛事的交付物，注释和用户可见字符串用中文，标识符用英文。
6. **不写脚手架/占位**：任何导出函数都必须有真实实现，禁止 `TODO`、`throw new Error('not implemented')`、返回假数据的桩。
7. **不要运行 `npm test` 全量**（其他切片文件可能尚未落盘，会红）。只跑你自己的用例：`npx vitest run src/<你的目录>`。类型检查可跑 `npx tsc --noEmit`，但**忽略不属于你文件的报错**（同样因为并行）。
8. 每个切片**必须**交付自己的 `*.test.ts`（真实断言，不是烟雾测试）。

## 关键契约摘要（详见 `core/types.ts` 与 `core/contracts.ts`）

- `Emotion = 'calm'|'joyful'|'tense'|'sorrowful'|'furious'|'fearful'|'suspicious'|'tender'`
- `resolveVoiceSettings(profile, emotion)` 已实现于 `core/types.ts`，直接复用。
- `MiniMaxTransport` 是唯一外呼边界：`chat()/speech()` 抛 `TransportError`（可降级）或 `UpstreamError`（不可降级）。
- 降级决策与重试**只在 `MiniMaxClient` 内**做。
- `DeterministicRandom.from(seed, step)` 提供可复现随机流；`hashText(text)` 提供稳定哈希。
- 常量：`MINIMAX_DEFAULTS`、`TEXT_LIMITS`、`VOICE_RANGES`、`EVAL_THRESHOLDS`、`MOCK_SEED`。

## 依赖方向（禁止反向）

```
core → personas → minimax → engine → eval → server/ui/cli
```

`eval` 可以 import `engine/personas/minimax/core`；`engine` 禁止 import `eval`。
