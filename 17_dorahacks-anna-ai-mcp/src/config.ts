import * as path from "node:path";

import type { LogLevel } from "./protocol/types.js";

export interface NetIntelConfig {
  transport: "stdio" | "http";
  port: number;
  host: string;
  offline: boolean;
  fixtureDir: string;
  cacheTtlMs: number;
  cacheMax: number;
  timeoutMs: number;
  logLevel: LogLevel;
  token?: string;
  allowAnyOrigin: boolean;
}

const LOG_LEVELS: readonly LogLevel[] = [
  "debug",
  "info",
  "notice",
  "warning",
  "error",
  "critical",
  "alert",
  "emergency",
];

const DEFAULTS = {
  transport: "stdio" as const,
  port: 8765,
  host: "127.0.0.1",
  offline: false,
  cacheTtlMs: 300_000,
  cacheMax: 256,
  timeoutMs: 8_000,
  logLevel: "info" as LogLevel,
  allowAnyOrigin: false,
};

export function defaultFixtureDir(): string {
  return path.resolve(__dirname, "..", "..", "fixtures", "feeds");
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw.trim() === "") {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || !Number.isInteger(value) || value <= 0) {
    return fallback;
  }
  return value;
}

function parseBool(raw: string | undefined, fallback: boolean): boolean {
  if (raw === undefined || raw.trim() === "") {
    return fallback;
  }
  const lowered = raw.trim().toLowerCase();
  if (lowered === "1" || lowered === "true") {
    return true;
  }
  if (lowered === "0" || lowered === "false") {
    return false;
  }
  return fallback;
}

function parseTransport(raw: string | undefined): "stdio" | "http" {
  return raw === "http" ? "http" : "stdio";
}

function parseLogLevel(raw: string | undefined): LogLevel {
  if (raw !== undefined && (LOG_LEVELS as readonly string[]).includes(raw)) {
    return raw as LogLevel;
  }
  return DEFAULTS.logLevel;
}

interface ArgvState {
  transport?: "stdio" | "http";
  port?: number;
  host?: string;
  offline?: boolean;
  fixtureDir?: string;
  cacheTtlMs?: number;
  cacheMax?: number;
  timeoutMs?: number;
  logLevel?: LogLevel;
  token?: string;
  allowAnyOrigin?: boolean;
}

function readFlagValue(argv: string[], index: number): string | undefined {
  const next = argv[index + 1];
  return next;
}

function parseArgv(argv: string[]): ArgvState {
  const state: ArgvState = {};
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    switch (flag) {
      case "--transport": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.transport = parseTransport(v);
          i += 1;
        }
        break;
      }
      case "--port": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.port = parsePositiveInt(v, DEFAULTS.port);
          i += 1;
        }
        break;
      }
      case "--host": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.host = v;
          i += 1;
        }
        break;
      }
      case "--offline": {
        state.offline = true;
        break;
      }
      case "--fixture-dir": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.fixtureDir = v;
          i += 1;
        }
        break;
      }
      case "--cache-ttl-ms": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.cacheTtlMs = parsePositiveInt(v, DEFAULTS.cacheTtlMs);
          i += 1;
        }
        break;
      }
      case "--cache-max": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.cacheMax = parsePositiveInt(v, DEFAULTS.cacheMax);
          i += 1;
        }
        break;
      }
      case "--timeout-ms": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.timeoutMs = parsePositiveInt(v, DEFAULTS.timeoutMs);
          i += 1;
        }
        break;
      }
      case "--log-level": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.logLevel = parseLogLevel(v);
          i += 1;
        }
        break;
      }
      case "--token": {
        const v = readFlagValue(argv, i);
        if (v !== undefined) {
          state.token = v;
          i += 1;
        }
        break;
      }
      case "--allow-any-origin": {
        state.allowAnyOrigin = true;
        break;
      }
      default:
        break;
    }
  }
  return state;
}

function readToken(env: Record<string, string | undefined>): string | undefined {
  const raw = env["NETINTEL_TOKEN"];
  if (raw === undefined || raw.trim() === "") {
    return undefined;
  }
  return raw;
}

export function loadConfig(env: Record<string, string | undefined>, argv: string[]): NetIntelConfig {
  const cli = parseArgv(argv);
  const config: NetIntelConfig = {
    transport: cli.transport ?? parseTransport(env["NETINTEL_TRANSPORT"]),
    port: cli.port ?? parsePositiveInt(env["NETINTEL_PORT"], DEFAULTS.port),
    host: cli.host ?? env["NETINTEL_HOST"] ?? DEFAULTS.host,
    offline: cli.offline ?? parseBool(env["NETINTEL_OFFLINE"], DEFAULTS.offline),
    fixtureDir: cli.fixtureDir ?? env["NETINTEL_FIXTURE_DIR"] ?? defaultFixtureDir(),
    cacheTtlMs: cli.cacheTtlMs ?? parsePositiveInt(env["NETINTEL_CACHE_TTL_MS"], DEFAULTS.cacheTtlMs),
    cacheMax: cli.cacheMax ?? parsePositiveInt(env["NETINTEL_CACHE_MAX"], DEFAULTS.cacheMax),
    timeoutMs: cli.timeoutMs ?? parsePositiveInt(env["NETINTEL_TIMEOUT_MS"], DEFAULTS.timeoutMs),
    logLevel: cli.logLevel ?? parseLogLevel(env["NETINTEL_LOG_LEVEL"]),
    allowAnyOrigin: cli.allowAnyOrigin ?? parseBool(env["NETINTEL_ALLOW_ANY_ORIGIN"], DEFAULTS.allowAnyOrigin),
  };
  const token = cli.token ?? readToken(env);
  if (token !== undefined) {
    config.token = token;
  }
  return config;
}
