import { createServer } from "node:http";
import type { Server } from "node:http";
import type { McpServer } from "../protocol/server.js";
import type { JsonRpcOutbound } from "../protocol/types.js";

export function runHttpTransport(server: McpServer, port = 3000): Server {
  const httpServer = createServer((req, res) => {
    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "POST, OPTIONS",
        "access-control-allow-headers": "content-type, authorization",
      });
      res.end();
      return;
    }

    if (req.method !== "POST") {
      res.writeHead(405, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "Method not allowed. Use POST /mcp" }));
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
  });

  httpServer.listen(port);
  return httpServer;
}
