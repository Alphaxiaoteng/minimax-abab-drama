/**
 * 静态资源服务：只读 src/src/ui/**，提供正确的 MIME 映射与路径穿越防护。
 *
 * 根目录经 import.meta.url 解析，绝不依赖 process.cwd()——
 * 容器里 WORKDIR、tsx 直接运行、vitest 工作目录三者各不相同，只有模块自身位置可靠。
 */

import { readFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path';

/** UI 产物根目录（src/src/ui）；测试与日志引用，避免第二份路径拼写 */
export const UI_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'ui');

/** 扩展名 → MIME：静态字面量查找表用 Record，未知扩展回落八进制流 */
const MIME_BY_EXT: Record<string, string> = {
  html: 'text/html; charset=utf-8',
  htm: 'text/html; charset=utf-8',
  js: 'text/javascript; charset=utf-8',
  mjs: 'text/javascript; charset=utf-8',
  css: 'text/css; charset=utf-8',
  webmanifest: 'application/manifest+json; charset=utf-8',
  json: 'application/json; charset=utf-8',
  svg: 'image/svg+xml',
  png: 'image/png',
  ico: 'image/x-icon',
  txt: 'text/plain; charset=utf-8',
  map: 'application/json; charset=utf-8',
};

/** 所有静态响应共用的安全头 */
const BASE_HEADERS: Readonly<Record<string, string>> = {
  'cache-control': 'no-cache',
  'x-content-type-options': 'nosniff',
};

export interface StaticResponse {
  readonly status: number;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: Uint8Array | null;
}

type PathOutcome =
  | { readonly ok: true; readonly filePath: string }
  | { readonly ok: false; readonly status: number; readonly reason: string };

const textEncoder = new TextEncoder();

/**
 * 把请求 URL 映射到 UI_ROOT 内的真实文件路径。
 * 防护顺序：拒绝空字节/反斜杠 → 解码 → 拒绝上跳段 → resolve 后再做一次包含性校验，
 * 这样 `%2e%2e`、`..//`、`....//` 之类的编码变体同样落在 403。
 */
function toFilePath(requestUrl: string): PathOutcome {
  const bare = requestUrl.split('?')[0]?.split('#')[0] ?? '/';
  if (bare.includes('\u0000') || bare.includes('\\')) {
    return { ok: false, status: 403, reason: '非法请求路径' };
  }

  let decoded: string;
  try {
    decoded = decodeURIComponent(bare);
  } catch {
    return { ok: false, status: 400, reason: 'URL 编码不合法' };
  }
  if (decoded.includes('\u0000')) return { ok: false, status: 403, reason: '非法请求路径' };
  if (!decoded.startsWith('/')) return { ok: false, status: 403, reason: '只接受站点绝对路径' };

  const segments: string[] = [];
  for (const raw of decoded.split('/')) {
    if (raw === '' || raw === '.') continue;
    if (raw === '..') return { ok: false, status: 403, reason: '禁止路径穿越' };
    // 含冒号的段是驱动器/方案写法（C:、file:），UI 目录不存在此类名字
    if (raw.includes(':')) return { ok: false, status: 403, reason: '禁止文件系统绝对路径' };
    segments.push(raw);
  }

  const candidate = resolve(UI_ROOT, ...segments);
  const contained = relative(UI_ROOT, candidate);
  if (isAbsolute(contained) || contained === '..' || contained.startsWith(`..${sep}`)) {
    return { ok: false, status: 403, reason: '禁止路径穿越' };
  }
  return { ok: true, filePath: candidate };
}

function reject(status: number, reason: string): StaticResponse {
  return {
    status,
    headers: { ...BASE_HEADERS, 'content-type': 'text/plain; charset=utf-8' },
    body: textEncoder.encode(`${status} ${reason}`),
  };
}

/** 读取站点静态资源；目录回落 index.html，越界 403，缺失 404 */
export async function serveStatic(requestUrl: string): Promise<StaticResponse> {
  const outcome = toFilePath(requestUrl);
  if (!outcome.ok) return reject(outcome.status, outcome.reason);

  let filePath = outcome.filePath;
  try {
    const info = await stat(filePath);
    if (info.isDirectory()) filePath = join(filePath, 'index.html');
    const bytes = await readFile(filePath);
    const ext = extname(filePath).slice(1).toLowerCase();
    return {
      status: 200,
      headers: {
        ...BASE_HEADERS,
        'content-type': MIME_BY_EXT[ext] ?? 'application/octet-stream',
      },
      body: bytes,
    };
  } catch (err) {
    const code = typeof err === 'object' && err !== null && 'code' in err ? String(err.code) : '';
    if (code === 'ENOENT' || code === 'ENOTDIR' || code === 'EACCES') {
      return reject(404, '资源不存在');
    }
    return reject(500, '静态资源读取失败');
  }
}