import { createServer } from "node:http";
import type { Server } from "node:http";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { McpServer } from "../protocol/server.js";
import type { JsonRpcOutbound } from "../protocol/types.js";

export function runHttpTransport(server: McpServer, port = 3000): Server {
  const httpServer = createServer(async (req, res) => {
    // CORS handling
    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
        "access-control-allow-headers": "content-type, authorization",
      });
      res.end();
      return;
    }

    // Serve MCP Inspector UI
    if (req.method === "GET" && req.url === "/") {
      try {
        const htmlPath = resolve(__dirname, "../../public/mcp-inspector.html");
        const html = readFileSync(htmlPath, "utf8");
        res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        res.end(html);
        return;
      } catch {
        res.writeHead(404, { "content-type": "text/plain" });
        res.end("MCP Inspector UI not found");
        return;
      }
    }

    // Handle MCP protocol endpoint (POST / or POST /mcp)
    const isMcpEndpoint = (req.url === "/" || req.url?.startsWith("/mcp"));
    if (isMcpEndpoint) {
      if (req.method !== "POST") {
        res.writeHead(405, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "Method not allowed. Use POST / or POST /mcp" }));
        return;
      }

      let body = "";
      req.setEncoding("utf8");
      req.on("data", (chunk: string) => {
        body += chunk;
      });

      req.on("end", async () => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(body);
        } catch {
          res.writeHead(400, { "content-type": "application/json" });
          res.end(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }));
          return;
        }

        const collected: JsonRpcOutbound[] = [];
        const tempSink = {
          emit: (msg: JsonRpcOutbound) => {
            collected.push(msg);
          },
        };

        server.setSink(tempSink);
        const immediate = server.handleInput(parsed);
        collected.push(...immediate);

        await server.idle();

        res.writeHead(200, {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        });
        if (collected.length === 1) {
          res.end(JSON.stringify(collected[0]));
        } else {
          res.end(JSON.stringify(collected));
        }
      });
    } else {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "Not found" }));
    }
  });

  httpServer.listen(port);
  return httpServer;
}
