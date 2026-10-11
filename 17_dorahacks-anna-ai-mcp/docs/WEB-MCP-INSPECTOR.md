# NetIntel MCP Inspector - Interactive Web Debug Console

## 🌐 Web-Based MCP Interactive Debug Workbench

A lightweight, zero-dependency web interface for visualizing and interacting with the NetIntel MCP server, modeled after Anthropic's official MCP Inspector.

### Features

#### 1. **Visual Tool Discovery**
- Browse all 5 tools with their complete Schema and documentation
- One-click tool selection to load parameter forms
- Real-time schema validation

#### 2. **Interactive Tool Invocation**
- Assemble parameters directly in the browser
- Execute tool calls with one click
- View raw JSON-RPC 2.0 request/response packets
- Measure round-trip latency (milliseconds)

#### 3. **Request/Response Log Viewer**
- Live log panel showing all JSON-RPC traffic
- Color-coded entries (request/blue, response/green, error/red)
- Syntax-highlighted JSON display
- Timing information per request

#### 4. **Security Policy Controls**
- 🔒 **Read-Only Mode**: Toggle to block write operations (fetch/cache/digest)
- 🛡️ **Security Guard**: Enable/disable policy enforcement
- Configuration viewer showing active policies

#### 5. **Server Status Indicator**
- Online/Offline badge with connection status
- Configurable server URL (default: http://localhost:3000/mcp)
- Protocol version negotiation display

---

## 📖 Usage

### Quick Start

```bash
# Start the HTTP server
npm run server

# Or run inspector mode (auto-opens help message)
npm run inspector
```

Then open your browser to: **http://localhost:3000**

### Manual Access

If you prefer to start both manually:

```bash
# Terminal 1: Start MCP server
node dist/src/cli.js --transport http --port 3000

# Terminal 2: Open browser
open http://localhost:3000
```

### Example Workflow

1. **Connect**: Click "Connect" button (server must be running on port 3000)
2. **Select Tool**: Click on any tool card (e.g., `net_search`)
3. **Configure Parameters**: 
   - Query: Enter search query (required)
   - Limit: Set number of results (default: 10)
   - Sources: Choose data sources (optional)
4. **Invoke**: Click "Invoke Tool" button
5. **Observe**: Watch JSON-RPC request/response in the log panel

---

## 🔧 Technical Details

### Architecture

```
┌─────────────┐     WebSocket/HTTP      ┌──────────────────┐
│ Browser     │ ◄────────────────────► │ MCP Server       │
│ (Client)    │     POST /mcp          │ (Node.js Process)│
├─────────────┤                        ├──────────────────┤
│ UI Layer    │                        │ Transport Layer  │
│ - Tool Cards│                        │ - HTTP Handler   │
│ - Form Gen  │                        │ - Request Parser │
│ - Log Panel │                        └──────────────────┘
├─────────────┤
│ State Mgmt  │
│ - Security  │
│ - Policies  │
└─────────────┘
```

### Security Policies

The MCP Inspector enforces enterprise-grade security rules:

| Policy | Description | Default |
|--------|-------------|---------|
| `readonlyMode` | Block write tools (fetch, cache, digest) | Off |
| `blockedTools` | Explicitly blocked tools list | `[]` |
| `originWhitelist` | Allowed CORS origins | localhost/127.0.0.1 |
| `rateLimitPerMinute` | Max requests per minute | 60 |
| `maxResponseSize` | Maximum response size | 1MB |

### Zero Dependencies

This entire UI is built with:
- Vanilla JavaScript (ES modules)
- Plain HTML/CSS
- No external libraries or frameworks
- Pure JSON-RPC 2.0 over HTTP transport

---

## 🎨 Design Principles

1. **Inspector Parity**: Match Anthropic's official MCP Inspector UX patterns
2. **Transparency**: Show raw protocol messages, not just formatted results
3. **Safety First**: Security guards prevent accidental destructive operations
4. **Offline-First**: Static HTML/JS served from local filesystem only
5. **Real-Time Feedback**: Instant visual confirmation of actions

---

## 🚀 Future Enhancements

- [ ] WebSocket streaming for long-running operations
- [ ] Export/import session configurations
- [ ] Multi-server management (saved connections)
- [ ] RRF scoring visualization (see docs/RRF-BREAKDOWN.md)
- [ ] Custom CSS themes

---

## 📝 License

MIT License • Part of NetIntel MCP Server project
