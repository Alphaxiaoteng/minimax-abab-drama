# NetIntel — 提交材料清单 (BUIDL Submission Checklist)

> 赛事：DoraHacks · Anna AI App Builder Program（智能体与 MCP Server 专项扶持）
> 赛事 ID：`dorahacks-anna-ai-agent-2026` · 截止：`2026-11-30`

## 交付物对照表（RULES.md §3）

| # | 官方要求 | 本项目产物 | 状态 |
|---|---|---|---|
| 1 | 源码仓库（整洁、含 Dockerfile / requirements.txt / package.json） | 本仓库；`Dockerfile`（多阶段、非 root、含 healthcheck）、`docker-compose.yml`、`package.json`（`dependencies: {}`）、`tsconfig.json`、`scripts/lint.js`（自建零依赖门禁）、`scripts/smoke.js`（一键端到端验证） | ✅ |
| 2 | 演示视频 2-5 分钟 | 分镜脚本 + 逐字旁白 + 录制检查清单见 `docs/DEMO-SCRIPT.md`（2:45） | 🎬 待录制 |
| 2 | 架构与说明文档（核心业务流程图、核心算法、技术选型理由） | `docs/ARCHITECTURE.md`（含 4 张 mermaid 图：业务时序、分层架构、并发扇出、生命周期状态机；排序公式推导；13 项技术选型对照表含被否方案） | ✅ |
| 3 | 在线体验 / 部署产物 / 一键运行脚本 | ① `npm ci && npm test && npm run smoke`（本地一键）② `docker compose up -d netintel-mcp`（HTTP 模式，可做在线体验链接）③ `mcp.json.example`（Claude Desktop / Cursor 一键接入）④ `docs/QUICKSTART.md`（复制粘贴级接入说明） | ✅ |
| 4 | JSON-RPC 接口验证脚本（RULES.md §4.2） | `npm run smoke` → `scripts/smoke.js`，对**真实子进程**走完整 NDJSON 会话并逐步断言 | ✅ |

## 制胜策略对齐（RULES.md §4）

| 策略 | 本项目的落地 |
|---|---|
| 打造标准 MCP Server | 逐条对齐 MCP `2025-06-18`；一致性声明含「规范条款 → 实现位置 → 验证方式」三列表，以及**3 处主动声明的偏差**（`docs/PROTOCOL-COMPLIANCE.md §9`） |
| 极简一键接入说明 | `docs/QUICKSTART.md`：60 秒跑通 + Claude Desktop / Cursor / Windsurf / Docker 四条接入路径 + 故障排查表 |
| JSON-RPC 接口验证脚本 | `scripts/smoke.js`：17 步断言，含错误路径与优雅退出 |
| 具备实际场景实用性 | 5 个工具 / 5 个资源（2 个模板）/ 3 个提示词；并发扇出 + 单源失败隔离 + 确定性排序 + TTL/LRU 缓存 + 离线 fixture 回放；协议内核 ~1000 行，100% 自测 |

## 评审可快速验证的点（建议写进 BUIDL 描述）

1. **零依赖**：`cat package.json` 里 `"dependencies": {}` 是字面事实，不是口号。
2. **协议是手写的**：`src/protocol/` 全为自实现，便于评审逐行核对规范条款。
3. **离线可复现**：测试在 `NETINTEL_OFFLINE=1` 下运行，且 `fetchImpl` 被替换为**抛错实现**——
   任何意外网络访问都会让测试立即失败。
4. **错误语义分层**：工具级失败 `isError:true`（模型可见可自纠）与协议级错误 `-32602/-32601/-32002`
   严格分离，符合 MCP 规范设计意图。
5. **降级可见**：单源故障返回 `partial:true` + `failedSources[]`，而非整体报错。
6. **确定性**：注入时钟、固定种子 PRNG、稳定全序排序——同一输入两次调用输出逐字节一致。

## 提审前自检

```bash
npm ci && npm run verify      # typecheck → lint → build → test → smoke
```

- [ ] `npm run verify` 全绿
- [ ] `docker build -t netintel-mcp:0.1.0 .` 成功，`docker compose --profile verify run --rm netintel-smoke` 通过
- [ ] `docs/` 四份文档已随仓库提交
- [ ] 演示视频已导出并上传
- [ ] BUIDL 页面已填写：仓库链接、Docker 镜像构建方式、`npm run smoke` 验证说明、在线体验说明（Docker HTTP 模式）
