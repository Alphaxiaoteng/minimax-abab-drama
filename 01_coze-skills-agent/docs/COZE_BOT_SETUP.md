# Coze（扣子）官方上架与评委体验指南 · COZE_BOT_SETUP

> 目标：从「本地一行命令导出 Schema」到「扣子上可对话的 Bot」，全程零门槛。
> 本插件集 **全程离线计算、零外部 API 依赖**，网关拉起即用，评委现场演示不受网络/配额影响。

包含 4 个工具：

| 工具 | 能力 | 网关路径 |
|---|---|---|
| `check_compliance` | 文案合规禁限词检测（广告法极限词/医疗宣称/金融承诺 + 合规改写） | `POST /tools/check_compliance` |
| `batch_check` | 批量文案合规体检（最多 200 条，风险分布 + 一句话结论） | `POST /tools/batch_check` |
| `analyze_reviews` | 多平台差评主题洞察（8 类主题归因、负面占比、改进清单） | `POST /tools/analyze_reviews` |
| `draft_reply` | 差评英文回复草稿（语气模板 + 渠道合规自检项） | `POST /tools/draft_reply` |

---

## 第 0 步：本地导出/校验 openapi.json（约 10 秒）

Schema 由代码单一事实来源（SSOT）机械生成，导出时严格通过 OpenAPI 3.0 结构校验：

```bash
cd 01_coze-skills-agent
PYTHONPATH=src python3 -m coze_skills.cli export-openapi \
  --out docs/coze-plugin-openapi.json \
  --title "Coze电商智能体插件" --version "1.0.0"
```

成功输出（stderr）：

```
Schema 校验通过 (OpenAPI 3.0.0): 4 个 operation / 14 个 tags / servers=http://127.0.0.1:8000 / 4 个 example payload
```

导出的 `openapi.json` 已包含：完整 `info`（title/version/description/contact）、`servers`、顶层 `tags` 与每个 operation 的 `tags`、**每个工具的 `example` 请求体**（可直接在扣子调试面板一键发起调用）。

需要 YAML 形态（扣子同样接受）时用同源导出，两次生成逐字节一致、可直接进版本库审阅：

```bash
PYTHONPATH=src python3 -m coze_skills.cli schema --format yaml \
  --out docs/coze-plugin-openapi.yaml --title "Coze电商智能体插件" --version "1.0.0"
```

### 导入前跑一遍兼容性自检（强烈建议）

`validate_openapi` 只保证**结构合法**（不会导入失败）；`audit` 查的是**平台可用性**——导入成功但大模型照样选错工具、填错参数，是插件上架后最常见的「能跑不好用」：

```bash
PYTHONPATH=src python3 -m coze_skills.cli audit            # 人读版
PYTHONPATH=src python3 -m coze_skills.cli audit --format json | jq .verdict
```

19 项检查（参数描述是否面向模型、枚举是否写明默认值、超时是否在平台预算内、example 是否真能调通、
导出文本是否含凭据样式片段……），当前产物 **18 pass / 1 info / 0 warning / 0 error**：

```
→ 18 pass / 1 info / 0 warning / 0 error :: 0 error · 0 warning —— 可直接导入扣子开放平台
```

唯一那条 `info` 是 `servers[0].url` 还是 `http://127.0.0.1:8000`（本地演示地址，上架前换成公网 HTTPS 即可），
它**不计入** warning。

## 第 1 步：拉起插件网关（评委演示需公网可达）

本地演示：

```bash
PYTHONPATH=src python3 -m uvicorn coze_skills.gateway:create_app --factory --host 0.0.0.0 --port 8000
curl -s http://127.0.0.1:8000/healthz   # {"status":"ok","tools":4,...}
```

> **零配置评委路径**：`coze_skills.gateway` 在纯 API 网关之上挂载了 Plugin Debugger Studio，浏览器直接打开
> `http://127.0.0.1:8000/` 即是深色工作台（**7 个面板** + 右上角「▶ 评委一键演示」），无需创建 Bot、无需导入 Schema：
> ①-④ 是四个技能；⑤「🤖 Coze Bot 演练」是本地多轮对话演练场；⑥「⚡ 容灾沙箱」一键注入异常；⑦「📦 Schema 导出」出自检清单与配置文件。
> 工作台前端调用的正是 `POST /tools/{name}` —— 与扣子插件上线后同一条链路，看到的结论逐字一致。
> 只想跑纯 API（例如给扣子做公网回源）时用 `coze_skills.core.server:create_app`，它不含 `/`、`/studio/*`、`/bot/*`、`/sim/*`、`/audit`、`/export/openapi`。

容器部署（镜像仅 2 个运行依赖，冷启动秒级）：

```bash
docker build -f src/Dockerfile -t coze-skills-gateway .
docker run -d -p 8000:8000 coze-skills-gateway
```

扣子云端无法访问你的 `127.0.0.1`，上架/云端演示前需把网关暴露为公网 HTTPS 地址（任意内网穿透或云主机均可），并重新导出：

```bash
PYTHONPATH=src python3 -m coze_skills.cli export-openapi --out openapi.json \
  --server-url "https://<你的公网域名>" --title "Coze电商智能体插件" --version "1.0.0"
```

网关契约（重要）：
- 所有工具统一 `POST + JSON body`，业务错误也返回 **HTTP 200 + `ok=false`**——避免扣子把非 2xx 当网络故障自动重试；
- 响应结构恒为 `{"ok": bool, "error": str|null, "data": {...}}`；
- `GET /openapi.coze.json` 可直接把线上 Schema 拉回本地比对；`GET /metrics` 提供调用成功率。

## 第 2 步：在扣子创建 Bot

1. 打开 [coze.cn](https://www.coze.cn)（海外版 [coze.com](https://www.coze.com)）→ 工作空间 → **创建 Agent（Bot）**；
2. 名称建议：`电商提效助手`；模型建议：扣子同款深度思考模型即可（本插件不依赖模型能力做计算，结果确定可复现）；
3. 人设（提示词）直接粘贴第 5 节的「评委体验 Prompt」。

## 第 3 步：导入 OpenAPI 3.0 Schema 创建插件

1. Bot 编排页 → **插件 → 添加插件 → 自定义插件 → 从 OpenAPI 导入**；
2. 版本号选 **OpenAPI 3.0**，把第 0 步导出的 `openapi.json` 内容整段粘贴（或上传文件）；
3. 导入成功后应自动识别 **4 个接口**（`/tools/check_compliance` 等）。若识别为 0 个，先看「常见问题」排查表；
4. 逐个接口确认「入参配置」：
   - 必填参数（如 `text` / `reviews` / `review` / `texts`）来源设为 **模型推断（LLM 推理）**；
   - 可选参数（`platform` / `marketplace` / `tone` / `top_n` / `refund_ready` / `extra_words`）保持默认；枚举值与 `default` 已写进 Schema，扣子会直接展示；
   - 每个接口都带 **example 请求体**，调试面板可一键填入示例直接「试运行」——这是评委最快验证链路的方式。

## 第 4 步：认证与变量映射

**认证（Authorization）**：
- 本网关鉴权策略为 **无认证**（离线工具、无敏感数据、错误不泄漏堆栈），导入时认证方式选「无 / None」即可；
- 若你自行加了网关保护，选 API Key：位置 `Header`、键名 `Authorization`、值放扣子的密钥管理，**不要把密钥写进 Schema 或对话**。

**变量映射**：
- 系统变量（`user_id`、`bot_id`、`conversation_id` 等）无需在 Schema 声明，插件调用时由扣子自动注入上下文字段，本插件不读取，保持留空即可；
- 若希望区分调用来源，可在扣子「变量」面板新建 `channel` 自定义变量，并在 Bot 提示词中引用 `{channel}`——参数映射层面无需改动 Schema；
- 参数映射优先级：对话抽取 > 固定值。演示场景全部走对话抽取（见下节触发词）。

## 第 5 步：4 个工具的典型对话触发词 + 评委体验 Prompt

### 典型触发词（发布后在对话窗口直接输入）

| 工具 | 触发话术示例 |
|---|---|
| check_compliance | 「帮我看看这条文案有没有违规：**这款面膜全网销量第一，药效显著，七天美白立竿见影！**」 |
| batch_check | 「这 3 条笔记文案帮我批量体检：①全网最低价错过再等一年 ②新中式缠花发簪手工绕线 ③亏本清仓仅此一天」 |
| analyze_reviews | 「分析这批差评：快递太慢了等了一周才到盒子都压烂了／鞋子偏小两码客服半天不回／The stitching came apart after one wash」 |
| draft_reply | 「给这条差评写封英文回复：Two stars. Delivery took three weeks and the package arrived damaged. 语气正式，可以承诺退款」 |

### 评委体验 Prompt（一次性展示 4 个工具，建议作为 Bot 开场人设）

把下面整段粘贴进 Bot「人设与回复逻辑」：

```text
你是「电商提效助手」，服务于跨境/国内电商运营，按以下规则使用插件（全程本地计算，结果确定可复现）：

1. 用户给单条商品文案/笔记 → 调用 check_compliance，platform 按上下文推断（小红书=xhs、抖音=douyin、淘宝=taobao、亚马逊=amazon），输出风险等级、命中词表（含位置与整改建议）和可直接替换的合规改写文本。
2. 用户给多条文案 → 调用 batch_check，先给一句话结论（N 条中 M 条高危），再逐条列风险。
3. 用户粘贴差评原文（一行一条，支持中英文）→ 调用 analyze_reviews，marketplace 按渠道推断，输出负面占比、Top 主题（含严重度与原文样例）和可落地中文改进清单。
4. 用户要求回复某条差评 → 调用 draft_reply，tone 默认 professional，用户提到「退款/补偿」时 refund_ready=true，输出英文草稿并附上该渠道的发送前合规自检项。

输出风格：结论先行、表格化、不编造数据；插件返回 ok=false 时如实转告原因，不重试轰炸。
开场白：「我是电商提效助手：贴文案我查违规，贴差评我归因，还能代写英文客服回复。全部离线计算，现场演示零依赖。」
```

**评委 3 分钟演示脚本**：
0. 兜底路径（公网穿透挂了 / 评委没账号）：`./scripts/demo.sh` 后浏览器打开它打印的 `http://127.0.0.1:<port>/`，右上角「▶ 评委一键演示」自动串场 ①合规高亮 → ③差评归因 → ④英文回复；
1. 贴第 5 节任一触发话术 → Bot 自动选工具并返回结构化结果；
2. 追问「改成淘宝平台再查一遍」→ 验证 `platform` 参数由对话动态抽取；
3. 让 Bot「把刚才那条差评写成 friendly 语气、不承诺退款」→ 验证 `tone` / `refund_ready` 映射；
4. 现场断网重试第 1 步 → 结果不变（离线确定性，这是本作品的核心卖点）。

> 第 2、3 步可以**先在本地彩排**：Studio 面板 ⑤ 用的就是上面这几句话术，本地跑通再去扣子复述一遍即可。

## 第 6 步（可选）：本地彩排 —— ⑤ Bot 演练场与 ⑥ 容灾沙箱

### ⑤ 「🤖 Coze Bot 演练」：不建 Bot 也能走完整条 Function Calling 链路

打开 `http://127.0.0.1:8000/` 切到 ⑤ 面板（或 `curl -s localhost:8000/bot/greet` 看首屏），
直接输入自然语言：

```bash
curl -s -X POST localhost:8000/bot/chat -H 'Content-Type: application/json' \
  -d '{"message":"帮我看看「这款面膜全网销量第一，药效显著」能不能发抖音"}'
```

一条回复卡片会摊开：命中的工具与信号词、实际发出的入参、**该工具的入参 JSON Schema**、
**Coze 插件调用的请求头样本**、往返延迟瀑布、以及 `context/prompt/tool_output/completion` 四类 Token 预估。
追问「换成淘宝平台再查一遍」会继承上一轮的业务内容、只覆盖 `platform` 一个参数 —— 正是扣子线上多轮的行为。

三点要说清的边界：

- 这里「大模型选工具」那一跳由 `core/bot.py` 的**确定性意图路由**替身完成，与线上唯一区别是选择环节不消耗 Token；
  Schema、参数校验、超时、响应结构、错误语义全部与扣子同源，换成真模型可整层替换而接口不变。
- 因此面板上的 Token 数字是**成本量级预估**（CJK 1 token/字、其余 4 字符/token），不是某家模型的精确计数，UI 也据此标注「预估」。
- 请求头里的 `Authorization` **永远只是 `Bearer ${COZE_PLUGIN_TOKEN}` 占位符**——真实密钥只在部署侧环境变量里，
  演练场与导出物中不落任何可用凭据（自检清单里就有一项专门扫这个）。

### ⑥ 「⚡ 容灾沙箱」：证明恶劣网络下的稳定性

10 类畸形入参一键注入（缺必填、容器类型错、枚举越界、数值越界、空必填、多余参数、数组元素类型错、
请求体不是对象、JSON 被截断、工具名不存在），**每一条都打到真实的 `POST /tools/{name}`**，
由线上同一条校验链拦截，所以红字诊断就是扣子调用失败时大模型看到的原文（零堆栈外泄）。

限流与超时两个仿真是无状态的，可反复点、也可脱离浏览器验收：

```bash
curl -s -o /dev/null -w '%{http_code}\n' 'localhost:8000/sim/throttle?attempt=0'   # 429 + Retry-After
curl -s -o /dev/null -w '%{http_code}\n' 'localhost:8000/sim/throttle?attempt=2'   # 200, 退避后恢复
curl -s -D- -o /dev/null 'localhost:8000/sim/timeout?ms=3000&budget=1200' | grep -i degrade   # 504 + X-Degrade
```

面板里的退避时长读服务端返回的 `Retry-After`，超时中断由浏览器 `AbortController` 真掐连接，
不是前端写死的假动画。

## 常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 导入后识别 0 个接口 | 确认 `openapi: "3.0.x"` 在顶层、`servers` 非空；直接用本仓库 `export-openapi` 产物，不要手改 |
| 调试面板试运行超时/失败 | `servers[0].url` 还是 `127.0.0.1`——扣子云端访问不到，重新导出时加 `--server-url` 指向公网 HTTPS |
| 提示 required 参数不存在 | Schema 与代码漂移；重跑 `export-openapi`，CI 中 `pytest tests/test_openapi_spec.py` 会拦截 |
| 平台反复重试调用 | 网关必须 HTTP 200 + `ok=false` 返回业务错误（本实现已内置），不要改成 4xx/5xx |
| 模型不调用插件 | 检查工具 `description` 是否被截断（描述是 Agent 选工具的依据）；或用第 5 节触发词显式点名 |

## 发布前检查清单

- [ ] `pytest tests/` 全绿（140 项，含 14 项 OpenAPI 完整性、15 项 Studio 验收、29 项 Bot 演练场、25 项容灾沙箱、18 项自检与导出；第三方严格校验项在装有 openapi-spec-validator 时执行）
- [ ] `./scripts/demo.sh` Exit 0（第 2 步导出 JSON+YAML 并跑 `cli audit` 闸门；第 5 步验收 7 个面板、Bot 链路、429/504 仿真与 `/audit`）
- [ ] `cli audit`（或 `GET /audit`）为 **0 error / 0 warning**，`verdict` 显示「可直接导入扣子开放平台」
- [ ] `export-openapi` 使用 `--server-url` 指向公网可达 HTTPS 网关
- [ ] 扣子调试面板 4 个接口 example 试运行全部 `ok=true`
- [ ] Bot 开场白 + 人设为第 5 节 Prompt
- [ ] 导出物（JSON/YAML/截图）不含任何真实凭据——自检项 `no-credential-in-schema` 会替你把关
