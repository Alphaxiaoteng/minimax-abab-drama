# 扣子 (Coze) AI 智能体与技能共创挑战赛 - 研发工程工作区

- **赛事 ID**：`coze-skills-agent-2026`
- **当前状态**：`已报名待提交`
- **报名截止**：`2026-10-31`
- **奖金激励**：`21万+ 现金奖池 + 苹果全家桶 + 商店长期分成`
- **官方链接**：[https://www.coze.cn/](https://www.coze.cn/)

## 🎯 交付目标
- [x] 完成架构设计与需求拆解 → [docs/architecture.md](docs/architecture.md)
- [x] 搭建 `src/` 核心功能代码（高复用性 Coze 插件 Schema + 垂类提效工具）
- [x] 编写自动化单元测试与功能验证脚本（39 项全绿）
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
│   │   ├── runner.py     # 执行层: 参数收敛/硬超时/异常兜底/调用日志
│   │   ├── server.py     # 网关层: FastAPI 路由 + /healthz + /metrics
│   │   └── cli.py        # 命令行: schema / list / selftest / invoke
│   └── tools/
│       ├── text_compliance.py  # check_compliance / batch_check
│       └── review_insight.py   # analyze_reviews / draft_reply
├── tests/                # 39 个测试（契约 / 工具 / 网关端到端）
├── Dockerfile            # 一键容器化部署（HEALTHCHECK 就绪）
├── requirements.txt      # 运行时仅 2 个依赖: fastapi + uvicorn
└── setup.py              # pip 安装与 coze-skills 命令入口
```

## 🚀 一键运行

```bash
cd src
pip install -r requirements.txt

# 1) 生成可直接粘贴进 Coze 控制台的插件 OpenAPI Schema
PYTHONPATH=. python3 -m coze_skills.cli schema --out ../docs/coze-plugin-openapi.json

# 2) 启动插件网关（Coze 侧填 http://<host>:8000 与 /openapi.coze.json）
PYTHONPATH=. python3 -m uvicorn coze_skills.core.server:create_app --factory --port 8000

# 3) 本地冒烟
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/invoke/check_compliance \
  -H 'Content-Type: application/json' -d '{"text":"全网第一！治疗脱发神器，100%有效"}'

# 4) 全量测试
pip install -r requirements-dev.txt && PYTHONPATH=. python3 -m pytest tests -q
```

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
| GET | `/healthz` | 健康检查 + 工具计数 |
| GET | `/openapi.coze.json` | 插件 Schema（Coze 控制台直接拉取） |
| GET | `/tools` | 工具清单与参数签名（不暴露 handler） |
| POST | `/invoke/{tool_name}` | 统一调用入口 |
| POST | `/tools/{tool_name}` | 同上（与 Schema 中声明的 path 对齐） |
| GET | `/metrics` | 调用量、成功率、平均耗时、最近失败 |

> 进度日志：`2026-10-10` 完成契约层→生成层→执行层→网关层四层骨架，落地 4 个垂类工具；39 项测试全绿；真实 uvicorn 进程 curl 验收通过；Schema 产出 `docs/coze-plugin-openapi.json`。
