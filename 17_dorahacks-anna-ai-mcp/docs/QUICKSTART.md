# NetIntel — 一键接入说明 (One-Command Integration)

> 交付物：**极简一键接入说明 + JSON-RPC 接口验证脚本**（RULES.md §4.2 点名要求）

---

## 0. 60 秒跑通

```bash
git clone <repo> && cd 17_dorahacks-anna-ai-mcp
npm ci                 # 只装 typescript，1 个包
npm run build          # tsc → dist/
npm test               # 编译后跑 node --test，全套 JSON-RPC 一致性测试
npm run smoke          # 用真实子进程跑一遍完整协议握手，打印逐步 PASS 表
```

期望输出（末行）：

```
SMOKE OK (17 steps)
```

`npm run smoke` 就是"JSON-RPC 接口验证脚本"：它 `spawn` 真实的
`node dist/src/cli.js --transport stdio`，通过 stdin/stdout 用**换行分隔的 JSON** 走完
`initialize → initialized → tools/list → resources/* → prompts/* → tools/call → 错误路径 → EOF`，
每一步断言协议字段并打印实测值。任何一步不符合 MCP 规范都会非零退出。

**零网络依赖**：`NETINTEL_OFFLINE=1` 时全部数据来自 `fixtures/feeds/**`，
测试与演示在任何离线机器上结果完全一致。

---

## 1. 接入 Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）
或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "netintel": {
      "command": "node",
      "args": ["/绝对路径/17_dorahacks-anna-ai-mcp/dist/src/cli.js", "--transport", "stdio"],
      "env": {
        "NETINTEL_LOG_LEVEL": "info",
        "NETINTEL_CACHE_TTL_MS": "300000"
      }
    }
  }
}
```

重启 Claude Desktop，在输入框的工具面板里应看到 5 个 `net_*` 工具。

## 2. 接入 Cursor / Windsurf

`~/.cursor/mcp.json`（Cursor）或 `mcp_config.json`（Windsurf）：

```json
{
  "mcpServers": {
    "netintel": {
      "command": "node",
      "args": ["/绝对路径/17_dorahacks-anna-ai-mcp/dist/src/cli.js"],
      "env": { "NETINTEL_OFFLINE": "1" }
    }
  }
}
```

完整样例见仓库根目录 `mcp.json.example`。

## 3. Docker（在线体验 / 部署产物）

```bash
# stdio 模式（给本地宿主）
docker build -t netintel-mcp:0.1.0 .
echo -n '' | docker run -i --rm netintel-mcp:0.1.0

# HTTP 模式（可被 URL 访问，用于在线体验链接）
NETINTEL_TOKEN=change-me docker compose up -d netintel-mcp
curl -s http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer change-me' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 400

# 容器内自证
docker compose --profile verify run --rm netintel-smoke
```

## 4. 手动验证 JSON-RPC（复制粘贴即可）

```bash
node dist/src/cli.js --transport stdio <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"net_search","arguments":{"query":"mcp server","limit":3}}}
EOF
```

单行复制版：

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | node dist/src/cli.js --transport stdio
```

---

## 5. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `NETINTEL_TRANSPORT` | `stdio` | `stdio` \| `http` |
| `NETINTEL_HOST` | `127.0.0.1` | HTTP 绑定地址（勿改 0.0.0.0，除非在容器内） |
| `NETINTEL_PORT` | `8765` | HTTP 端口 |
| `NETINTEL_OFFLINE` | `0` | `1` = 只读 fixtures，不发任何网络请求 |
| `NETINTEL_FIXTURE_DIR` | `<repo>/fixtures/feeds` | fixture 根目录 |
| `NETINTEL_CACHE_TTL_MS` | `300000` | 缓存 TTL（5 分钟） |
| `NETINTEL_CACHE_MAX` | `256` | 缓存 LRU 上限 |
| `NETINTEL_TIMEOUT_MS` | `8000` | 单次上游 HTTP 超时 |
| `NETINTEL_LOG_LEVEL` | `info` | `debug`…`emergency`（syslog 八级） |
| `NETINTEL_TOKEN` | 未设置 | 设置后 HTTP 必须带 `Authorization: Bearer <token>` |
| `NETINTEL_ALLOW_ANY_ORIGIN` | `0` | `1` = 关闭 Origin 白名单校验 |

---

## 6. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| Claude 工具面板没有 `net_*` | 路径含空格未加引号 / 未 `npm run build` | 用绝对路径并确认 `dist/src/cli.js` 存在 |
| stdout 出现非 JSON 行 | 某处 `console.log` 泄漏 | 本项目静态门禁 `npm run lint` 会拦住；诊断信息一律走 stderr |
| `-32600 Server not initialized` | 忘了发 `notifications/initialized` | 按 §4 的顺序补齐 |
| 工具返回 `isError:true` 且提到上游失败 | 真实网络/限流（GitHub 未鉴权 60 req/h） | 设 `NETINTEL_OFFLINE=1` 或稍后重试；`net_sources` 可查看各源可用状态 |
| HTTP `403 Origin not allowed` | 浏览器/客户端 Origin 不在白名单 | 加入白名单或 `NETINTEL_ALLOW_ANY_ORIGIN=1`（仅本地调试） |
