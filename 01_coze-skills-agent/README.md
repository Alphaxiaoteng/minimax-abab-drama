# 扣子 (Coze) AI 智能体与技能共创挑战赛 - 研发工程工作区

- **赛事 ID**：`coze-skills-agent-2026`
- **当前状态**：`已报名待提交`
- **报名截止**：`2026-10-31`
- **奖金激励**：`21万+ 现金奖池 + 苹果全家桶 + 商店长期分成`
- **官方链接**：[https://www.coze.cn/](https://www.coze.cn/)

## 🎯 交付目标
- [x] 完成架构设计与需求拆解 → [docs/architecture.md](docs/architecture.md)
- [x] 搭建 `src/` 核心功能代码（高复用性 Coze 插件 Schema + 垂类提效工具）
- [x] 编写自动化单元测试与功能验证脚本（140 项全绿：29 Bot 演练场 + 25 容灾沙箱 + 18 交付自检 + 15 Studio 验收 + 14 OpenAPI 完整性）
- [x] Coze 官方上架与评委体验指南 → [docs/COZE_BOT_SETUP.md](docs/COZE_BOT_SETUP.md)
- [x] Plugin Debugger Studio 可视化调试工作台（浏览器打开 `/` 即用，零配置，7 个面板）
- [x] Coze Bot 对话演练场 + 企业级容灾沙箱 + OpenAPI 一键导出/兼容性自检（0 error 0 warning）
- [ ] 录制演示视频 (2-5 分钟清晰操作)
- [ ] 提交材料归档至 `docs/` 并完成官方提审

> 详细比赛规则、打分指标与避开红海的破局打法，请参阅同目录下的 [RULES.md](RULES.md)。

---

## 🧱 工程结构

```text
src/
├── coze_skills/
│   ├── core/
│   │   ├── spec.py       # 契约层: Param / ToolSpec / ToolResult（零第三方依赖）
│   │   ├── registry.py   # 注册表: 自动发现 tools 下模块级 TOOLS 常量
│   │   ├── schema.py     # 生成层: ToolSpec → OpenAPI 3.0 + 本地结构自检
│   │   ├── yamlout.py    # 导出层: 零依赖确定性 YAML（同输入同字节, 可进 git diff）
│   │   ├── audit.py      # 上架层: 19 项 Coze 兼容性自检清单（可用性, 不只是结构合法）
│   │   ├── bot.py        # 演练层: 确定性意图路由 + 卡片组装 + Token 估算（Function Calling 替身）
│   │   ├── chaos.py      # 容灾层: 10 类畸形入参用例 + 429/504 仿真（无状态, 可复现）
│   │   ├── runner.py     # 执行层: 参数收敛/硬超时/异常兜底/调用日志
│   │   └── server.py     # 网关层: FastAPI 纯 API 路由 + /healthz + /metrics
│   ├── cli.py            # 命令行: export-openapi / schema / audit / list / selftest / invoke
│   ├── static/           # Plugin Debugger Studio: 深色单页工作台（零构建、零外部依赖）
│   │   ├── index.html    # 7 个面板: 4 个技能 + Bot 演练 + 容灾沙箱 + Schema 导出
│   │   ├── studio.css    # 高亮下划线 / 风险徽章 / 主题进度条 / 对话卡片样式
│   │   └── app.js        # 直连同源 POST /tools/{name}，与扣子调用链路一致
│   ├── tools/
│   │   ├── text_compliance.py  # check_compliance / batch_check
│   │   └── review_insight.py   # analyze_reviews / draft_reply
│   └── gateway.py        # 交付入口: core.server 之上挂载 Studio、Bot、容灾与导出面板
├── Dockerfile            # 一键容器化部署（HEALTHCHECK 就绪）
├── requirements.txt      # 运行时仅 2 个依赖: fastapi + uvicorn
└── setup.py              # pip 安装与 coze-skills 命令入口（含 static/ 资源）

tests/                    # 140 个测试: 契约/工具/网关端到端/OpenAPI 完整性/Studio 15/
                          # Bot 演练场 29/容灾沙箱 25/上架自检与导出 18
```

## 🚀 一键运行

```bash
cd src
pip install -r requirements.txt

# 1) 导出完整 OpenAPI 3.0 Schema（含 info/servers/tags + 每个工具 example payload）
PYTHONPATH=. python3 -m coze_skills.cli export-openapi --out ../docs/coze-plugin-openapi.json
#    YAML 同源导出（零依赖确定性 emitter, 两次生成逐字节一致, 可直接进 git diff）:
PYTHONPATH=. python3 -m coze_skills.cli schema --format yaml --out ../docs/coze-plugin-openapi.yaml

# 1b) 上架兼容性自检（19 项, 目标 0 error / 0 warning）
PYTHONPATH=. python3 -m coze_skills.cli audit

# 2) 启动插件网关（自带 Studio 工作台；Coze 侧填 http://<host>:8000 与 /openapi.coze.json）
PYTHONPATH=. python3 -m uvicorn coze_skills.gateway:create_app --factory --port 8000
#    浏览器打开 http://127.0.0.1:8000/ 即是 Plugin Debugger Studio

# 3) 本地冒烟
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/invoke/check_compliance \
  -H 'Content-Type: application/json' -d '{"text":"全网第一！治疗脱发神器，100%有效"}'

# 4) 全量测试（140 项；src/pytest.ini 的 testpaths 已指向 ../tests）
pip install -r requirements-dev.txt && PYTHONPATH=. python3 -m pytest -q
#    或在仓库根目录一条命令（推荐, 与 CI 一致）: make test-01
```

## 🖥️ Plugin Debugger Studio（评委零配置入口）

`gateway.py` 在纯 API 网关之上挂载 `src/coze_skills/static/`，评委打开根路径即用，**无需装 Python、无需配 Bot**：

| 面板 | 交互 | 数据源 |
|---|---|---|
| ① 文案合规检测 | 输入即高亮（200ms 防抖，红/橙/蓝三级下划线）· 风险等级徽章 · 命中词→建议替换 · 原文↔改写侧边对比 · 一键复制 | `POST /tools/check_compliance` |
| ② 批量文案体检 | 一行一条 → 高/中/低分布徽章 + 逐条 Top 命中词 | `POST /tools/batch_check` |
| ③ 差评主题洞察 | 8 大主题占比进度条（未命中主题补 0% 灰条）· 原文引用 · 中文动作 + 英文标签改进清单 | `POST /tools/analyze_reviews` |
| ④ 差评英文回复 | 语气 × 渠道 × 补偿开关 → 草稿 + 发送前合规自检 | `POST /tools/draft_reply` |
| ⑤ 🤖 Coze Bot 演练 | 自然语言多轮对话 → 意图识别 → 触发工具 → 结构化卡片；卡片折叠露出入参 JSON Schema、Coze 请求头样本、往返延迟瀑布、Token 四类消耗 | `GET /bot/greet` · `POST /bot/chat` |
| ⑥ ⚡ 容灾沙箱 | 10 类畸形入参一键注入 · 429 限流退避（读服务端 `Retry-After`）· 504 超时降级回退 · 客户端 `AbortController` 预算封顶 · 红字友好诊断零堆栈 | `GET /sim/cases` · `GET /sim/throttle` · `GET /sim/timeout` + 真实 `POST /tools/{name}` |
| ⑦ 📦 Schema 导出 | 兼容性自检清单 19 项（0 error / 0 warning 才可上线）· JSON/YAML 一键下载 | `GET /audit` · `GET /export/openapi?format=json\|yaml` |

右上角「▶ 评委一键演示」按 ①→③→④ 自动串场。前端与扣子走完全同一条 `/tools/{name}` 链路，因此工作台看到的结论与 Bot 上线后逐字一致。

> ⑤ 面板里「大模型选工具」这一跳由 `core/bot.py` 的确定性意图路由替身完成——与线上唯一的区别是选择环节不消耗 Token，
> Schema、参数校验、超时、响应结构、请求头与错误语义全部与扣子同源；替身给出的入参仍是**不可信输入**，照样过真实校验链。

## 🧩 已上架工具（4 个 / 12 个参数）

| 工具 | 分类 | 作用 |
|---|---|---|
| `check_compliance` | compliance | 小红书/电商文案禁限词检测（绝对化/医疗/金融/正则/软性词五类），输出 risk_level + 改写文本 |
| `batch_check` | compliance | 批量合规体检（≤200 条），结果与输入等长同序，附一句话结论 |
| `analyze_reviews` | insight | 多平台差评主题洞察（8 类主题、中英混排、多标签归因），输出占比与可执行改进建议 |
| `draft_reply` | insight | 差评英文回复草稿，三种语气 × 歉意分级，保留 `{{support_email}}` 占位符 |

## 📐 接口规范

所有接口统一返回 `{"ok": bool, "error": str|null, "data": object}`，**业务错误也走 HTTP 200**（避免 Coze 把非 2xx 判为网络故障触发重试重压下游）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | Plugin Debugger Studio 工作台（由 `gateway.py` 挂载，`core.server` 纯 API 无此路由） |
| GET | `/studio/{file}` | 工作台静态资源（studio.css / app.js；index.html 由 `/` 直接返回） |
| GET | `/healthz` | 健康检查 + 工具计数 |
| GET | `/openapi.coze.json` | 插件 Schema（Coze 控制台直接拉取） |
| GET | `/tools` | 工具清单与参数签名（不暴露 handler） |
| POST | `/invoke/{tool_name}` | 统一调用入口 |
| POST | `/tools/{tool_name}` | 同上（与 Schema 中声明的 path 对齐，也是工作台的前端入口） |
| GET | `/metrics` | 调用量、成功率、平均耗时、最近失败 |
| GET | `/bot/greet` | Bot 演练场开场白 + 4 条快问快答（`core.server` 无此路由） |
| POST | `/bot/chat` | 跑一整轮对话：意图路由 → 真实 runner → 结构化卡片；入参不可信，照样过校验链 |
| GET | `/sim/cases` | 10 类畸形入参用例清单（`core.chaos` 单点声明，前端不另抄一份） |
| GET | `/sim/throttle` | 429 限流仿真：前 N 次 429 + `Retry-After`，之后 200 + `recovered_after`（无状态） |
| GET | `/sim/timeout` | 504 超时仿真：`ms > budget` → 504 + `X-Degrade: cached-result`，否则 200（无状态） |
| GET | `/audit` | 19 项 Coze 上架兼容性自检清单（带 runner，连 example 能否跑通都查） |
| GET | `/export/openapi` | Schema 导出，`?format=json\|yaml`、`?download=false`（YAML 与 JSON 同源同字节序） |

> 演示面（`/bot/*`、`/sim/*`、`/audit`、`/export/openapi`）都是**加法旁路**：`core/server.py` 那份纯 API 网关不含它们，
> 容灾面板注入畸形入参时打的仍是真实的 `POST /tools/{name}`，因此它验证的是上线后的同一条校验链，而不是一段模拟代码。

> 进度日志：`2026-10-10` 完成契约层→生成层→执行层→网关层四层骨架，落地 4 个垂类工具；真实 uvicorn 进程 curl 验收通过；Schema 产出 `docs/coze-plugin-openapi.json`。
> `2026-10-11` 深度打磨上架链路：`export-openapi` 导出补齐 info/servers/tags 与 4 个工具 example payload（并通过 openapi-spec-validator 第三方严格校验），新增 `tests/test_openapi_spec.py`（14 项）后全量测试绿（53 项，最小环境 1 项可选依赖自动 skip）；发布《COZE_BOT_SETUP.md》零门槛导入指南。
> `2026-10-11` 交付 Plugin Debugger Studio：`static/` 深色单页工作台（实时高亮下划线 + 风险徽章 + 原文↔改写对比 + 8 主题进度条 + 中英改进清单 + 评委一键演示），`gateway.py` 挂载静态目录与 `GET /`；真实 Chromium 逐项点检后修掉 3 个肉眼可见缺陷（进度条依赖 rAF 被后台节流停在 0%、原文对比丢失末次命中后的尾巴、负面词表过窄导致整屏差评只算 13%），并补 `tests/test_studio.py` 至 11 项钉死这些回归，全量测试 64 项绿（Exit Code 0），`scripts/demo.sh` 第 5 步同步验收 Studio。
> `2026-10-11` 大厂上线标准第二阶段深度 Polish：Studio 扩到 **7 个面板**——⑤「🤖 Coze Bot 演练」多轮对话场（`core/bot.py` 确定性意图路由替身 Function Calling 一跳，卡片折叠露出入参 Schema / Coze 请求头样本 / 延迟瀑布 / 四类 Token 估算，追问只改参数也能继承上一轮）；⑥「⚡ 容灾沙箱」（`core/chaos.py` 10 类畸形入参一键注入真实 `/tools/{name}`、429 退避读 `Retry-After`、504 降级 + `X-Degrade`、`AbortController` 客户端预算封顶，全程零堆栈外泄）；⑦「📦 Schema 导出」（`core/audit.py` 19 项兼容性自检 **0 error / 0 warning** + `core/yamlout.py` 零依赖确定性 YAML 导出）。新增 `tests/test_bot.py` 29 项、`test_chaos.py` 25 项、`test_delivery.py` 18 项并扩 `test_studio.py`，全量 **140 项绿**；真实 Chromium 点检 ⑤⑥⑦ 面板 `console` 零事件；`docs/coze-plugin-openapi.yaml` 入库并带漂移守卫。
