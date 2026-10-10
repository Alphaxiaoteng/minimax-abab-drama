import type { McpServer } from "../protocol/server.js";

export function runStdioTransport(server: McpServer): void {
  server.setSink({
    emit: (msg) => {
      process.stdout.write(JSON.stringify(msg) + "\n");
    },
  });

  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    buf += chunk;
    let idx = buf.indexOf("\n");
    while (idx >= 0) {
      const line = buf.slice(0, idx).replace(/\r$/, "").trim();
      buf = buf.slice(idx + 1);
      if (line.length > 0) {
        try {
          const parsed = JSON.parse(line) as unknown;
          const immediate = server.handleInput(parsed);
          for (const resp of immediate) {
            process.stdout.write(JSON.stringify(resp) + "\n");
          }
        } catch {
          const parseError = {
            jsonrpc: "2.0",
            id: "__parse_error__",
            error: { code: -32700, message: "Parse error" },
          };
          process.stdout.write(JSON.stringify(parseError) + "\n");
        }
      }
      idx = buf.indexOf("\n");
    }
  });

  process.stdin.on("end", () => {
    server.close();
    process.exit(0);
  });
}
