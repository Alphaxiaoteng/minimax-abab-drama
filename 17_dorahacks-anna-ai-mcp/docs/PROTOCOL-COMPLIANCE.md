# NetIntel — MCP 协议一致性声明 (Protocol Compliance Statement)

> 目标规范：**Model Context Protocol `2025-06-18`**（也兼容协商到 `2025-03-26` / `2024-11-05`）
> 传输：**stdio**（主）与 **Streamable HTTP**（次）
> 本文件逐条列出「规范要求 → 实现位置 → 验证方式」，并**如实列出所有偏差**。

---

## 1. 基础协议 (Base Protocol)

| 规范条款 | 要求 | 实现 | 验证 |
|---|---|---|---|
| 消息格式 | 全部消息遵循 JSON-RPC 2.0 | `src/protocol/jsonrpc.ts` | `tests/jsonrpc.envelope.test.ts` |
| 请求 ID | `id` 必须为 string 或 integer，**不得为 `null`** | `src/protocol/validate.ts`：`id === null` → `-32600` | `tests/protocol.core.test.ts` |
| 响应 | `result` 与 `error` **必须二选一，不得同时出现** | `jsonrpc.ts` 只暴露 `success`/`failure` 两个构造器 | `tests/jsonrpc.envelope.test.ts`（全量出站消息扫描） |
| 错误码为整数 | `error.code` 为 integer | `src/protocol/errors.ts` 常量表 | `tests/jsonrpc.errors.test.ts` |
| 通知无 ID | 通知**不得**含 `id`；接收方**不得**回响应 | `dispatch.ts` 通知分支永不 emit 响应 | `tests/jsonrpc.envelope.test.ts` |
| `_meta` | 允许保留字段；实现不得对保留键做假设 | 仅读取 `_meta.progressToken`，其余原样忽略 | `tests/protocol.lifecycle.test.ts` |

---

## 2. 生命周期 (Lifecycle)

| 规范条款 | 实现 | 验证 |
|---|---|---|
| `initialize` 必须是首次交互 | 非 `ping` 请求在 `initialize` 前到达 → `-32600 "Server not initialized"`，`data:{method}` | `tests/protocol.lifecycle.test.ts` |
| 客户端在收到 `initialize` 响应前不应发其他请求 | 服务端**主动强制**（不是静默忽略） | 同上 |
| **版本协商**：支持则回显客户端版本，否则回自身最新支持版本 | `SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18","2025-03-26","2024-11-05"]`；`"1.0.0"` → 回 `"2025-06-18"` | `tests/protocol.lifecycle.test.ts` |
| 收到 `initialized` 前不得发请求（`ping`/`logging` 除外） | 状态机 `await-initialized` 阶段的出站队列只允许 `notifications/message` | `src/protocol/server.ts` |
| 能力协商后只使用已协商能力 | 能力集合固定声明（见 §7）；未声明能力的请求 → `-32601` | `tests/jsonrpc.errors.test.ts` |
| 关闭：客户端关闭 stdin，等待退出，必要时 SIGTERM/SIGKILL | stdin EOF → abort 在途 handler → 退出码 **0**；`SIGTERM` 亦优雅退出 | `tests/transport.stdio.test.ts` |
| 请求应设超时，超时应发取消通知并停止等待 | 服务端对上游 HTTP 使用 8s 超时；客户端侧超时由宿主负责（本 server 不在客户端角色） | `src/net/http.ts` |

**`initialize` 永不被拒绝**：即使客户端声明不支持任何版本，也回 `2025-06-18` 并交由客户端决定是否断开
（规范原文：*"If the client does not support the version in the server's response, it SHOULD disconnect."* —— 决定权在客户端）。

---

## 3. 传输 (Transports)

### stdio

| 规范条款 | 实现 | 验证 |
|---|---|---|
| 消息以换行分隔，**不得包含内嵌换行** | 每行一条 `JSON.stringify` 结果；`\n`/`\r` 在 JSON 字符串中必然被转义 | `tests/jsonrpc.envelope.test.ts`（对每条出站消息断言无 `\n`） |
| 服务器**不得**向 `stdout` 写任何非 MCP 消息 | 全仓静态门禁：`scripts/lint.js` 规则 L1/L2 禁止 `console.*` 与 `process.stdout`（`src/transports/stdio.ts` 为唯一白名单） | `npm run lint` |
| 服务器**可以**向 `stderr` 写 UTF-8 日志 | 诊断 NDJSON 走 `NETINTEL_LOG_LEVEL` 过滤后写入 stderr | `tests/transport.stdio.test.ts`（断言 stderr 有日志、stdout 无杂质） |
| 客户端**不得**向 stdin 写非 MCP 消息 | 收到非法输入不回写错误以外内容；非法 JSON → `-32700` | `tests/jsonrpc.errors.test.ts` |

### Streamable HTTP

| 规范条款 | 实现 | 验证 |
|---|---|---|
| 单一 endpoint 同时支持 POST 与 GET | `POST /mcp`；`GET /mcp` → `405` + `Allow: POST, DELETE` | `tests/transport.http.test.ts` |
| 客户端 POST 需 `Accept` 同时含 json 与 event-stream | 服务端返回 `Content-Type: application/json`（单对象分支），**不强制**校验 `Accept`；不要求 SSE 的客户端同样可用 | `tests/transport.http.test.ts` |
| 请求 → 200 单 JSON 对象 或 SSE 流 | **返回单 JSON 对象**（本 server 工具均为有限时长、不流式） | 同上 |
| 通知/响应 → `202 Accepted` 空 body | 已实现 | 同上 |
| 无法接受的输入 → 4xx | 非法 JSON → `400` + JSON-RPC error body | 同上 |
| **必须**校验 `Origin` 以防 DNS rebinding | 白名单：`http://localhost:*` / `http://127.0.0.1:*` / `vscode-webview://*`；不在白名单 → `403` | 同上 |
| 本地运行时**应**绑 `127.0.0.1` | 默认 `NETINTEL_HOST=127.0.0.1` | 同上 |
| **应**实现认证 | `NETINTEL_TOKEN` 设置后强制 `Authorization: Bearer`，缺失 → `401` | 同上 |
| `MCP-Protocol-Version` 头 | 缺失 → 沿用会话协商版本；存在但不支持 → `400` | 同上 |
| DELETE 终止会话 | `DELETE /mcp` → `204` | 同上 |
| session id | **未实现** `Mcp-Session-Id`（无状态设计） | 见 §9 偏差 D2 |

---

## 4. 服务器能力：工具 (Tools)

| 规范条款 | 实现 | 验证 |
|---|---|---|
| 支持工具**必须**声明 `tools` 能力 | `capabilities.tools` | `tests/protocol.lifecycle.test.ts` |
| `tools/list` 支持分页 | 不透明游标，页大小 50 | `tests/protocol.pagination.test.ts` |
| 工具集在同连接上**不得**因其他请求而改变 | 注册表在启动时冻结；`listChanged:false` | 注册表 `register*` 重复即抛；无运行时注册路径 |
| **应**返回确定性顺序（利缓存/提示词缓存命中） | 插入序固定，测试断言两次调用逐字节一致 | `tests/protocol.pagination.test.ts` |
| `tools/call` 未知工具 → JSON-RPC error | `-32602`，`data:{name}` | `tests/tools.registry.test.ts` |
| 参数非法 → JSON-RPC error | 自写 JSON Schema 子集校验 → `-32602`，`data:{errors:[{path,message}]}` | `tests/tools.validation.test.ts` |
| 工具执行期错误 → `result.isError:true`（**不是** JSON-RPC error） | 分发表捕获任意异常 → `content:[{type:"text",text:"Tool execution failed: …"}]` + `isError:true` | `tests/tools.registry.test.ts` |
| `outputSchema` 声明后 `structuredContent` **必须**符合该 schema | 每次返回前用同一校验器自检；不符 → `isError:true` 并说明不匹配点 | `src/protocol/server.ts` |
| 返回结构化内容时**应**同时在 text block 中附 JSON 序列化 | 追加 `TextContent` 内容为 `JSON.stringify(structuredContent)` | `tests/tools.registry.test.ts` |
| 安全：校验输入 / 限流 / 净化输出 | 输入校验见上；列表页大小封顶；`net_fetch` 限 http(s)+长度+字节数+超时；输出全部经 `JSON.stringify` | `src/tools/net_fetch.ts` |

---

## 5. 服务器能力：资源与提示词

| 规范条款 | 实现 | 验证 |
|---|---|---|
| 支持资源**必须**声明 `resources` | `capabilities.resources.subscribe = true`，`listChanged = false` | `tests/protocol.lifecycle.test.ts` |
| `resources/list` / `resources/templates/list` 支持分页 | 已实现（页大小 50） | `tests/protocol.pagination.test.ts` |
| URI 模板遵循 RFC 6570 | `netintel://feed/{key}`、`netintel://item/{source}/{id}`，`{name}` 简单展开 | `tests/resources.prompts.test.ts` |
| 资源不存在 → `-32002` | 未注册 URI 且无模板匹配 → `-32002`，`data:{uri}` | 同上 |
| `resources/subscribe` 后变更应发 `notifications/resources/updated` | 缓存被写入且命中订阅前缀时广播 | `tests/resources.prompts.test.ts` |
| 资源**必须**校验 URI | 模板匹配前做长度/字符集检查；`item` 模板对 `source` 做枚举白名单 | 同上 |
| 支持提示词**必须**声明 `prompts` | `capabilities.prompts.listChanged = false` | `tests/protocol.lifecycle.test.ts` |
| `prompts/get` 未知名称 / 缺必填参数 → `-32602` | 已实现，缺参带 `data:{argument}` | `tests/resources.prompts.test.ts` |
| 提示词输入**必须**校验以防注入 | 参数经 `String()` 归一化并限制长度；输出为 `TextContent`，不做任何模板求值 | 同上 |

---

## 6. 工具函数 (Utilities)

| 规范条款 | 实现 | 验证 |
|---|---|---|
| 支持补全**必须**声明 `completions` | `capabilities.completions = {}` | `tests/protocol.lifecycle.test.ts` |
| `completion/complete` 支持 `ref/prompt` 与 `ref/resource` | 两者均实现 | `tests/resources.prompts.test.ts` |
| 补全值 ≤ 100 项，含 `total`/`hasMore` | 全部截断到 100 并正确置 `hasMore` | 同上 |
| 未知 ref / 未知参数 → `-32602` | 已实现 | 同上 |
| 支持日志**必须**声明 `logging` | `capabilities.logging = {}` | `tests/protocol.lifecycle.test.ts` |
| syslog 八级 | `debug < info < notice < warning < error < critical < alert < emergency` | `src/protocol/server.ts` 级别过滤 |
| `logging/setLevel` 非法级别 → `-32602` | 已实现 | `tests/protocol.lifecycle.test.ts` |
| 日志不得含凭证 | 仅记录 URL 主机、计数、错误摘要；`Authorization` 头永不入日志 | 代码审查 + `src/net/http.ts` |
| `ping` 必须立即返回空结果 | `result: {}` | `tests/protocol.core.test.ts` |
| 取消：`notifications/cancelled` 应停止处理并不再响应 | `AbortController` 中断在途 handler，且**抑制其响应** | `tests/protocol.lifecycle.test.ts` |
| 取消：未知/已完成请求的取消通知应被忽略 | 静默忽略，不报错 | 同上 |
| `initialize` **不得**被取消 | `cancelRequest` 对 `initialize` 的 id 不生效 | 同上 |
| 进度：仅当请求携带 `progressToken` 才发通知 | `_meta.progressToken` 存在才 emit | `tests/protocol.lifecycle.test.ts` |
| 进度值**必须**递增 | 单调递增断言；不递增则不发送 | 同上 |
| 进度通知**必须**在完成后停止 | 结果发出后不再 emit | 同上 |

---

## 7. 本服务器声明的能力（逐字节）

```json
{
  "tools":       { "listChanged": false },
  "resources":   { "subscribe": true, "listChanged": false },
  "prompts":     { "listChanged": false },
  "logging":     {},
  "completions": {}
}
```

**刻意未声明**：`experimental`。**刻意未实现**：客户端能力 `roots` / `sampling` / `elicitation`
——本 server 不发起任何服务端→客户端请求，因此不需要它们。这是设计取舍而非遗漏：
不发起采样请求意味着**无需客户端具备任何特殊能力**即可使用全部功能，最大化可接入面。

---

## 8. 错误码矩阵（实现 vs 规范）

| 码 | 语义 | 本 server 触发点 |
|---|---|---|
| `-32700` | Parse error | 无法解析的 JSON 行 |
| `-32600` | Invalid Request | `jsonrpc != "2.0"` / `id === null` / `result` 与 `error` 并存 / 批量数组 / `initialize` 前的非 ping 请求 / 非法游标所在信封 |
| `-32601` | Method not found | 未注册方法；未声明能力的请求 |
| `-32602` | Invalid params | 工具参数校验失败（`data.errors`）/ 未知工具（`data.name`）/ 未知提示词 / 缺必填参数（`data.argument`）/ 非法日志级别 / 非法游标 |
| `-32603` | Internal error | 分发表捕获到的未预期异常（`data.message`，**不含堆栈**） |
| `-32002` | Resource not found | `resources/read` / `resources/subscribe` 指向未注册且无模板匹配的 URI（`data.uri`） |

---

## 9. 偏差声明 (Declared Deviations)

> 以下 3 处是本实现与规范字面要求的**唯一**差异，均为可辩护的工程决策，且已被测试固定行为。

**D1 — Parse error 的 `id` 取值。**
规范规定请求 `id` 不得为 `null`，但 JSON-RPC 2.0 在解析失败时无法得知 `id`。
本实现返回 `{"jsonrpc":"2.0","id":"__parse_error__","error":{"code":-32700,"message":"Parse error"}}`，
使用哨兵字符串而非 `null`，从而同时满足「必须返回 -32700」与「id 不得为 null」两条约束。
同理：非法对象信封使用 `"__invalid_request__"`，批量数组使用 `"__batch__"`。
客户端**应当**把这三个哨兵值视为"服务端无法关联到具体请求"。

**D2 — 未实现 `Mcp-Session-Id` 会话管理。**
规范中 session management 为 `MAY`（可选）。本 server 无状态：每个 POST 都是自包含的
JSON-RPC 消息，`initialize` 的协商结果按连接（进程）保存，`DELETE /mcp` 幂等返回 `204`。
选择理由：stdio 是主传输且天然单会话；HTTP 侧无状态使水平扩展与压测无需粘性会话。
影响：客户端不会收到 `Mcp-Session-Id` 头，也不需要回传；不符合规范 `MUST` 的条款为零。

**D3 — SSE 流式响应未实现。**
规范允许「请求 → 返回 `application/json` 单对象」或「开启 SSE 流」二选一。
本 server 的所有工具调用均为有限时长（上游 8s 超时 + 页大小封顶），无长时任务，
因此统一走单 JSON 对象分支。`GET /mcp` 依规范返回 `405`（明确表示本 endpoint 不提供 SSE 流），
而不是返回空的 `text/event-stream`。当未来引入长时任务（如全站抓取）时，将改为 SSE。

**非偏差说明**：本 server 不实现 `resources/subscribe` 的 `listChanged` 与资源列表变更通知，
因为资源集合在启动时静态确定；能力声明中如实置 `listChanged: false`，属规范允许范围。
