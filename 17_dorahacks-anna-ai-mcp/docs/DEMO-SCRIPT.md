# NetIntel — 演示视频脚本 (2:45 Demo Script)

> 交付物：**2-5 分钟高保真操作录屏**（RULES.md §3）
> 目标时长：**2 分 45 秒**。全程 1920×1080，字号 ≥ 16pt，录屏工具建议 QuickTime 或 `asciinema` + 终端美化。

**录制前必做（一次性，不录进视频）**

```bash
npm ci && npm run build && npm test        # 确认全绿，避免录制中翻车
export NETINTEL_OFFLINE=1                  # 演示 determinism，网络抖动不影响
clear
```

**终端布局**：左侧 60% 终端 A（跑 server 的原始 JSON-RPC），右侧 40% 终端 B（跑审阅结论）。
光标保持可见，命令**逐字敲入**（不要粘贴），节奏 ≈ 每分钟 180 字。

---

## 分镜表 (Shot List)

| # | 时间 | 画面 | 旁白（中文） | 屏幕动作 |
|---|---|---|---|---|
| 0 | 0:00–0:08 | 标题卡 | "Agent 想用实时情报，但每接一个数据源就要写一套胶水代码。" | 黑底白字标题：`NetIntel · MCP Server · 5 tools · 3 sources · 0 dependencies` |
| 1 | 0:08–0:25 | 痛点 | "HN、GitHub、arXiv 的返回结构完全不同，而且没排序、没去重、没缓存。结果是 Agent 的上下文被噪声塞满，答案质量反而下降。" | 三分屏各贴一段上游原始 JSON 片段 |
| 2 | 0:25–0:42 | 架构图 | "NetIntel 把它们收敛成一层可排序、可去重、可缓存的情报流，用 MCP 标准协议交付。" | 展示 `docs/ARCHITECTURE.md` 的 mermaid 架构图 |
| 3 | 0:42–1:00 | 代码体量 | "整个过程只用了 0 个运行时依赖，协议层手写。先看证明。" | 终端 A：`cat package.json \| grep -A2 dependencies` → `"dependencies": {}` |
| 4 | 1:00–1:20 | **一键验证** | "一条命令，对真实子进程走完整个 JSON-RPC 会话。" | 终端 A：`npm run smoke` → 展示 PASS 表滚动 → `SMOKE OK (17 steps)` ← **高亮这一刻** |
| 5 | 1:20–1:40 | 真实握手 | "协议是手写的，所以可以逐行验证。这是 initialize。" | 终端 A 粘贴三行 heredoc，展示 `InitializeResult`（能力集合 + serverInfo），指一下 `"protocolVersion":"2025-06-18"` |
| 6 | 1:40–2:05 | **核心价值** | "这是重点：一次调用，三源并发、失败隔离、排序、去重。" | `tools/call net_search {query, sources:全部, limit:3}` → 逐行圈出 `"partial":false`、`items[0].score`、`total:14`（返回 3 条但 total 是 14，说明截断语义正确） |
| 7 | 2:05–2:20 | 韧性 | "单源挂掉不会让整个调用失败，Agent 能看到降级信息自己决定重试。" | 设 `NETINTEL_TIMEOUT_MS=1` 重跑同一调用 → 展示 `"partial":true` + `failedSources[{source,error}]`，而 `isError` 仍是 `false` |
| 8 | 2:20–2:32 | 错误语义 | "工具级失败和协议级失败严格分开——这正是 MCP 的设计意图。" | 先调不存在的工具 → `-32602`；再调 `net_fetch` 一个 404 → `isError:true`。并列展示两者 |
| 9 | 2:32–2:45 | 收尾 CTA | "协议一致性、错误矩阵、fuzz、传输都有测试固定行为。五个工具，三种数据源，零依赖。" | 终端 B：`npm test` 尾部统计（`# pass N` / `# fail 0`）→ 定格 `docs/ARCHITECTURE.md` 的目录树截图 |

---

## 逐字旁白稿（可直接朗读，约 400 字）

> （0:00）Agent 要回答"最近 MCP 生态发生了什么"，就得接 Hacker News、GitHub、arXiv——每接一个源，
> 就要写一套解析、去重、排序的胶水代码。
>
> （0:10）更麻烦的是，这三个源的返回结构完全不同，而且不带排序和缓存。结果就是噪声灌满上下文，
> Agent 的答案质量反而下降。
>
> （0:25）NetIntel 把这一层收敛掉了：三个源统一成一层可排序、可去重、可缓存的情报流，
> 通过 Model Context Protocol 标准协议暴露出去。
>
> （0:42）先看一个硬指标：运行时依赖是**零**。协议层（JSON-RPC 2.0 和 MCP 消息层）是手写的，
> 所以每一行都可以审计。
>
> （1:00）一条命令就能验证：`npm run smoke` 会启动真实的 server 子进程，
> 用换行分隔的 JSON 走完 initialize、工具发现、资源读取、提示词、错误路径，再优雅退出。
> 每一步都断言协议字段——这就是题目要求的 JSON-RPC 接口验证脚本。
>
> （1:20）协议是手写的，所以我们能逐行验证。这是 initialize 的应答：协商到 2025-06-18，
> 声明五项能力，并带上自描述的 serverInfo。
>
> （1:40）现在看核心价值。一次 `net_search`：三个源**并发**扇出，每源独立超时和缓存，
> 然后统一去重、按相关性加时效性加权排序。注意 `total` 是 14 而只返回了 3 条——截断语义是明确的。
>
> （2:05）如果某个源挂了会怎样？整个调用**不会**失败。它返回 `partial:true` 和具体的失败源，
> Agent 可以看到降级信息，自己决定要不要重试。这比直接报错可用性高一个量级。
>
> （2:20）工具执行失败和协议错误是严格分开的：调用不存在的工具是协议错误 `-32602`；
> 而 `net_fetch` 遇到 404 是工具级失败，`isError` 为 true 但 JSON-RPC 仍是成功响应——
> 这正是 MCP 规范的设计意图，让模型看得见错误并自我纠正。
>
> （2:32）协议一致性、错误码矩阵、模糊测试、两种传输都有测试固定行为。
> 五个工具，三个数据源，零依赖。

---

## 录制要点清单 (Pre-flight Checklist)

- [ ] `npm run smoke` 已确认输出 `SMOKE OK`（视频里不允许出现 FAIL）
- [ ] 终端字号 ≥ 16pt，行宽 ≤ 100 列，关闭换行
- [ ] `NETINTEL_OFFLINE=1` 已 export，确保第 6、7 镜结果稳定
- [ ] 第 7 镜的 `NETINTEL_TIMEOUT_MS=1` 记得在同一 shell 内设，之后 `unset`
- [ ] 第 9 镜的 `npm test` 已提前跑过一次（缓存预热），保证录制时输出在 3 秒内完成
- [ ] 关闭通知、隐藏其他窗口、清空滚动历史
- [ ] 录屏帧率 ≥ 30fps，文字类画面避免压缩糊化；导出 H.264 / 8Mbps

## 剪辑提示

- 第 5 镜可加 0.3s 高亮框标注 `protocolVersion` 与 `capabilities`。
- 第 6 镜在 `total: 14` 与 `items` 长度 `3` 上加并排小字：`截断语义`。
- 第 8 镜左右分屏固定，左侧打红标 `协议错误 −32602`，右侧打黄标 `工具错误 isError:true`。
- 结尾 3 秒定格：仓库根目录 + 一行 `npm ci && npm test && npm run smoke`。
- 全程不加背景音乐，或使用 −24dB 的极轻环境音；旁白始终为主导。
