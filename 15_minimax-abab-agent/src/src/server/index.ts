/**
 * HTTP 服务器入口：用 node:http 原生实现，零第三方依赖。
 * 组合 api.ts（纯函数请求处理器）与 static.ts（静态资源服务）。
 */

import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { ServerHandle, ServerOptions } from '../core/contracts.js';
import { createApiDeps, handleApiRequest } from './api.js';
import type { ApiDeps, ApiResponsePayload } from './api.js';
import { serveStatic } from './static.js';
import type { StaticResponse } from './static.js';

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString('utf-8');
}

/** 把统一响应体写回 HTTP：body 可能是 string（JSON）或 Uint8Array（静态字节） */
function writeHttp(res: ServerResponse, payload: ApiResponsePayload | StaticResponse): void {
  res.writeHead(payload.status, payload.headers);
  const body = 'body' in payload ? payload.body : '';
  if (typeof body === 'string') {
    res.end(body, 'utf-8');
  } else if (body === null) {
    res.end();
  } else {
    res.end(Buffer.from(body));
  }
}

/** 启动 HTTP 服务器。port=0 时随机分配；host 默认 0.0.0.0 以便容器与手机访问 */
export async function startServer(options: ServerOptions): Promise<ServerHandle> {
  const host = options.host ?? '0.0.0.0';
  const deps: ApiDeps = createApiDeps(options.overrides);

  const server = createServer((req, res) => {
    // 请求处理内部错误不能击穿 socket，一律走 500 兜底
    void (async () => {
      try {
        const url = req.url ?? '/';
        if (url.startsWith('/api/')) {
          const body = await readBody(req);
          const resp = await handleApiRequest({ method: req.method ?? 'GET', url, body }, deps);
          writeHttp(res, resp);
          return;
        }
        writeHttp(res, await serveStatic(url));
      } catch {
        writeHttp(res, {
          status: 500,
          headers: { 'content-type': 'text/plain; charset=utf-8' },
          body: 'Internal Server Error',
        });
      }
    })();
  });

  await new Promise<void>((resolveListen, rejectListen) => {
    server.once('error', rejectListen);
    server.listen(options.port, host, () => resolveListen());
  });

  const addr = server.address();
  if (addr === null || typeof addr === 'string') {
    server.close();
    throw new Error('服务器未能绑定到可用 TCP 地址');
  }

  return {
    port: addr.port,
    url: `http://${host}:${addr.port}`,
    close: () =>
      new Promise<void>((resolveClose, rejectClose) => {
        server.closeAllConnections();
        server.close((err) => {
          if (err) rejectClose(err);
          else resolveClose();
        });
      }),
  };
}

/** 直接运行入口：`npx tsx src/server/index.ts`；作为库被 import 时不触发 */
const isMainModule =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMainModule) {
  const port = Number(process.env.PORT ?? 8787);
  const handle = await startServer({ port, host: process.env.HOST ?? '0.0.0.0' });
  console.log(`沉浸式互动推理剧 Agent 服务已启动：${handle.url}`);
  console.log(`健康检查：${handle.url}/api/health`);

  const shutdown = (): void => {
    void handle.close().then(() => process.exit(0));
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}