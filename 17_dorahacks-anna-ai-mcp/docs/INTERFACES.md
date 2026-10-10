# NetIntel — 接口规范 (Interface Reference)

> 所有 JSON 均为**实测原样**摘录（去掉省略部分），可直接作为客户端的契约文档。
> 协议基线：MCP `2025-06-18`。错误码语义见 `PROTOCOL-COMPLIANCE.md §8`。

---

## 1. 工具一览 (Tools)

| 工具名 | 标题 | 用途 | 只读 | 开放世界 |
|---|---|---|---|---|
| `net_search` | Search open-source intelligence | 跨源检索并排序去重，返回结构化情报流 | ✅ | ✅ |
| `net_digest` | Digest a topic over a time window | 给定时间窗生成 Markdown 简报 | ✅ | ✅ |
| `net_fetch` | Fetch and clean a single URL | 抓取单页并清洗为纯文本/Markdown | ✅ | ✅ |
| `net_sources` | List intelligence sources | 查看数据源可用性与缓存配置 | ✅ | ❌ |
| `net_cache` | Inspect or purge the response cache | 查看/清理进程内缓存 | ✅ | ❌ |

---

### 1.1 `net_search`

**输入 schema**

```json
{
  "type": "object",
  "properties": {
    "query":   { "type": "string", "minLength": 1, "maxLength": 512 },
    "sources": { "type": "array", "items": { "type": "string", "enum": ["hackernews", "github", "arxiv"] } },
    "limit":   { "type": "integer", "minimum": 1, "maximum": 50, "default": 10 },
    "since":   { "type": "string", "description": "ISO 8601 日期，只保留此时间之后的条目" },
    "tags":    { "type": "array", "items": { "type": "string" } },
    "format":  { "type": "string", "enum": ["json", "markdown"], "default": "json" }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

**输出 `outputSchema`（`structuredContent`）**

```json
{
  "type": "object",
  "properties": {
    "query":    { "type": "string" },
    "sources":  { "type": "array", "items": { "type": "string" } },
    "offline":  { "type": "boolean" },
    "partial":  { "type": "boolean" },
    "failedSources": {
      "type": "array",
      "items": { "type": "object", "properties": { "source": { "type": "string" }, "error": { "type": "string" } }, "required": ["source", "error"] }
    },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id":          { "type": "string" },
          "source":      { "type": "string" },
          "title":       { "type": "string" },
          "url":         { "type": "string" },
          "author":      { "type": "string" },
          "publishedAt": { "type": "string" },
          "summary":     { "type": "string" },
          "tags":        { "type": "array", "items": { "type": "string" } },
          "metrics":     { "type": "object" },
          "score":       { "type": "number" }
        },
        "required": ["id", "source", "title", "url", "score"]
      }
    },
    "total":   { "type": "integer" },
    "tookMs":  { "type": "number" },
    "cache":   { "type": "object" }
  },
  "required": ["query", "sources", "offline", "partial", "failedSources", "items", "total", "tookMs", "cache"]
}
```

**调用样例**

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"net_search","arguments":{"query":"mcp server","sources":["hackernews","arxiv"],"limit":3}}}
```

**响应样例**（`structuredContent` 摘录，`items` 按 `score` 降序）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      { "type": "text", "text": "{\"query\":\"mcp server\",\"total\":14,...}" }
    ],
    "structuredContent": {
      "query": "mcp server",
      "sources": ["hackernews", "arxiv"],
      "offline": true,
      "partial": false,
      "failedSources": [],
      "items": [
        {
          "id": "41234567",
          "source": "hackernews",
          "title": "Show HN: A zero-dependency MCP server in TypeScript",
          "url": "https://example.com/mcp-zero-deps",
          "author": "algernon",
          "publishedAt": "2026-10-09T11:22:00.000Z",
          "summary": "…",
          "tags": ["show_hn", "story"],
          "metrics": { "score": 412, "comments": 96 },
          "score": 6.83
        }
      ],
      "total": 14,
      "tookMs": 3.41,
      "cache": { "hits": 2, "misses": 0, "sets": 2, "entries": 2 }
    },
    "isError": false
  }
}
```

**边界行为**

| 输入 | 行为 |
|---|---|
| 未知源名 | `-32602`，`data.errors[].path = "sources[0]"` |
| `limit: 0` / `limit: 51` | `-32602`（超出 `minimum`/`maximum`） |
| `limit: 3.5` | `-32602`（`integer` 类型违约） |
| 单源上游失败 | **成功**响应，`partial:true`，`failedSources:[{source,error}]`，其余源正常返回 |
| 全部源失败 | **成功**响应，`items:[]`，`partial:true`，`failedSources` 含三条；**不**置 `isError` |
| 缓存命中 | `cache.hits` 递增，`tookMs` 显著下降 |

---

### 1.2 `net_digest`

输入：`{query*, sources[], lookback_hours: 1..168 = 24, limit: 1..50 = 10}`（`additionalProperties:false`）

输出 `structuredContent`：`{query, window:{since,until,hours}, sources, itemCount, markdown, items:FeedItem[]}`

`markdown` 结构固定，便于 LLM 直接引用：

```markdown
# Topic digest: model context protocol
> window 2026-10-09T12:00:00.000Z → 2026-10-10T12:00:00.000Z (24h) · 8 items · sources: hackernews, arxiv

## 1. <标题>
- source: `hackernews` · score: `6.83` · 2026-10-09T11:22:00.000Z
- <上游摘要，最多 400 字符>
- <https://…>
```

---

### 1.3 `net_fetch`

输入：`{url* (http/https, ≤2048), max_bytes: 1024..524288 = 65536, format: "text"|"markdown" = "text"}`

输出：`{url, status, ok, contentType, bytes, truncated, title?, text}`

| 场景 | 行为 |
|---|---|
| 非 2xx | **成功**响应 + `isError:true`，text 中以 `HTTP <status>` 开头说明 |
| 超时 / DNS 失败 | **成功**响应 + `isError:true`，text 为失败原因 |
| `max_bytes` 截断 | `truncated:true`，`bytes` = 实际返回字节数 |
| 非 http(s) scheme（如 `file://`） | `-32602`（schema `pattern` 拒绝） |
| HTML | 剥离标签、折叠空白；`format:"markdown"` 时前置 `# <title>` |

---

### 1.4 `net_sources`

输入：无参数（`{"type":"object","properties":{},"additionalProperties":false}`）

输出：

```json
{
  "offline": true,
  "cache": { "ttlMs": 300000, "maxEntries": 256 },
  "sources": [
    { "id": "hackernews", "label": "Hacker News", "homepage": "https://news.ycombinator.com/", "available": true },
    { "id": "github",     "label": "GitHub",       "homepage": "https://github.com/",            "available": true, "lastError": "rate limited" }
  ]
}
```

`available:false` 时**必然**携带 `lastError`（字符串，已剥离凭证）。

---

### 1.5 `net_cache`

输入：`{action*: "stats"|"clear"|"purge", key?: string}`

| action | 前置条件 | 输出 |
|---|---|---|
| `stats` | — | `{action:"stats", stats:CacheStats}` |
| `clear` | — | `{action:"clear", stats:CacheStats, cleared:<n>}` |
| `purge` | `key` 必填且存在 | `{action:"purge", stats:CacheStats, cleared:1}`；`key` 缺失/不存在 → `isError:true` |

`CacheStats = {hits, misses, sets, entries}`

---

## 2. 资源 (Resources)

| URI | 类型 | mimeType | 内容 |
|---|---|---|---|
| `netintel://catalog` | 静态 | `application/json` | `{generatedAt, sources, tools, resourceTemplates, limits}` — 自描述清单 |
| `netintel://sources` | 静态 | `application/json` | 同 `net_sources` 输出 |
| `netintel://cache/stats` | 静态 | `application/json` | `CacheStats` + 配置 |
| `netintel://feed/{key}` | 模板 | `text/markdown` | 该缓存键对应的 Markdown 情报流 |
| `netintel://item/{source}/{id}` | 模板 | `application/json` | 单条 `RawItem` |

**订阅**：`resources/subscribe` 仅对 `netintel://feed/{key}` 有效（未知 URI → `-32002`）。
订阅后，任何写入同一缓存键的 `net_search`/`net_digest` 都会触发：

```json
{"jsonrpc":"2.0","method":"notifications/resources/updated","params":{"uri":"netintel://feed/hackernews|a1b2c3d4e5f60718"}}
```

**读取样例**

```json
{"jsonrpc":"2.0","id":9,"method":"resources/read","params":{"uri":"netintel://catalog"}}
```
```json
{"jsonrpc":"2.0","id":9,"result":{"contents":[{"uri":"netintel://catalog","mimeType":"application/json","text":"{\"generatedAt\":\"…\"}"}]}}
```

---

## 3. 提示词 (Prompts)

| 名称 | 参数 | 产出 |
|---|---|---|
| `brief_topic` | `topic*`, `lookback_hours?`(默认 24), `sources?` | 1 条 user 消息：主题 + 严格 Markdown 骨架（TL;DR / Key developments / Signal vs noise / Open questions），并指示模型调用 `net_search`/`net_digest` |
| `compare_sources` | `topic*` | 1 条 user 消息：按源分别调用 `net_search`，以表格输出各源**一致**与**冲突**之处 |
| `explain_item` | `url*` | 1 条 user 消息：调用 `net_fetch` 后为非专业读者解释，并单列 "What changed for builders" |

```json
{"jsonrpc":"2.0","id":11,"method":"prompts/get","params":{"name":"brief_topic","arguments":{"topic":"MCP adoption","lookback_hours":"48"}}}
```
```json
{"jsonrpc":"2.0","id":11,"result":{
  "description":"Produce a decision-ready brief on a topic using live open-source intelligence.",
  "messages":[{"role":"user","content":{"type":"text","text":"…"}}]}}
```

**补全**

```json
{"jsonrpc":"2.0","id":12,"method":"completion/complete",
 "params":{"ref":{"type":"ref/prompt","name":"brief_topic"},"argument":{"name":"sources","value":"git"}}}
```
```json
{"jsonrpc":"2.0","id":12,"result":{"completion":{"values":["github"],"total":1,"hasMore":false}}}
```

支持的补全点：`ref/prompt` 的 `sources`（前缀过滤三源）与 `lookback_hours`（`1|6|12|24|72|168`）；
`ref/resource` 的 `netintel://feed/{key}`（按缓存键，最多 100 项）。

---

## 4. 通知 (Notifications)

| 方法 | 触发条件 | 载荷 |
|---|---|---|
| `notifications/message` | `logging/setLevel` 级别以下被过滤 | `{level, logger, data}` |
| `notifications/progress` | 请求 `params._meta.progressToken` 存在 | `{progressToken, progress, total?, message?}`，**严格递增** |
| `notifications/resources/updated` | 已订阅的 feed 缓存键被写入 | `{uri}` |
| `notifications/cancelled` | 客户端取消（**入站**） | `{requestId, reason?}` |

---

## 5. 错误回应样例（逐字节）

```jsonc
// 未知方法
{"jsonrpc":"2.0","id":7,"error":{"code":-32601,"message":"Method not found","data":{"method":"tools/nope"}}}

// 未知工具
{"jsonrpc":"2.0","id":8,"error":{"code":-32602,"message":"Unknown tool: nope","data":{"name":"nope"}}}

// 参数校验
{"jsonrpc":"2.0","id":9,"error":{"code":-32602,"message":"Invalid arguments",
  "data":{"errors":[{"path":"limit","message":"must be <= 50"}]}}}

// 资源不存在
{"jsonrpc":"2.0","id":10,"error":{"code":-32002,"message":"Resource not found","data":{"uri":"netintel://nope"}}}

// 未初始化
{"jsonrpc":"2.0","id":11,"error":{"code":-32600,"message":"Server not initialized","data":{"method":"tools/list"}}}

// 解析失败（哨兵 id，见 PROTOCOL-COMPLIANCE §9 D1）
{"jsonrpc":"2.0","id":"__parse_error__","error":{"code":-32700,"message":"Parse error"}}
```

---

## 6. 验证这套接口

```bash
npm run build && npm test     # 全套 JSON-RPC 一致性 / 错误矩阵 / fuzz / 传输测试
npm run smoke                 # 对真实子进程跑一遍上面所有调用并打印 PASS 表
```
