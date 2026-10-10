import { applyDefaults, validateAgainstSchema } from "../tools/validate.js";
import type { ResponseCache } from "../net/cache.js";
import {
  INVALID_PARAMS,
  INVALID_REQUEST,
  JsonRpcError,
  RESOURCE_NOT_FOUND,
  invalidParams,
  invalidRequest,
  methodNotFound,
  resourceNotFound,
} from "./errors.js";
import { failure, fromError, notification, success } from "./jsonrpc.js";
import { paginate } from "./pagination.js";
import type { Registry } from "./registry.js";
import { decodeEnvelope, isRecord } from "./validate.js";
import {
  LATEST_PROTOCOL_VERSION,
  SUPPORTED_PROTOCOL_VERSIONS,
} from "./types.js";
import type {
  CallToolResult,
  ContentBlock,
  Implementation,
  JsonRpcNotification,
  JsonRpcOutbound,
  JsonRpcRequest,
  LogLevel,
  ResourceReadResult,
  ServerCapabilities,
  ServerContext,
} from "./types.js";

export interface ServerSink {
  emit(msg: JsonRpcOutbound): void;
}

export type ServerPhase = "await-initialize" | "await-initialized" | "ready" | "closed";

export interface DispatchOptions {
  registry: Registry;
  cache: ResponseCache;
  serverInfo: Implementation;
  instructions: string;
  pageSize?: number;
  now?: () => number;
  sink?: ServerSink;
}

interface InFlight {
  controller: AbortController;
  cancelled: boolean;
  lastProgress: number;
  promise: Promise<void>;
}

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  notice: 30,
  warning: 40,
  error: 50,
  critical: 60,
  alert: 70,
  emergency: 80,
};

const CAPABILITIES: ServerCapabilities = {
  tools: { listChanged: false },
  resources: { subscribe: true, listChanged: false },
  prompts: { listChanged: false },
  logging: {},
  completions: {},
};

function isStringId(value: unknown): value is string | number {
  return typeof value === "string" || typeof value === "number";
}

function textBlock(text: string): ContentBlock {
  return { type: "text", text };
}

export class Dispatcher {
  private readonly registry: Registry;
  private readonly cache: ResponseCache;
  private readonly serverInfo: Implementation;
  private readonly instructions: string;
  private readonly pageSize: number;
  private readonly nowFn: () => number;
  private sink: ServerSink | undefined;
  private serverPhase: ServerPhase = "await-initialize";
  private negotiatedVersion: string | undefined;
  private clientCapabilities: Record<string, unknown> = {};
  private currentLevel: LogLevel = "info";
  private readonly inflight = new Map<string | number, InFlight>();
  private readonly subscriptions = new Set<string>();
  private queue: JsonRpcNotification[] = [];
  private shutdownEmitted = false;

  constructor(opts: DispatchOptions) {
    this.registry = opts.registry;
    this.cache = opts.cache;
    this.serverInfo = opts.serverInfo;
    this.instructions = opts.instructions;
    this.pageSize = opts.pageSize !== undefined && opts.pageSize > 0 ? opts.pageSize : 50;
    this.nowFn = opts.now ?? (() => Date.now());
    this.sink = opts.sink;
  }

  get phase(): ServerPhase {
    return this.serverPhase;
  }

  get isReady(): boolean {
    return this.serverPhase === "ready";
  }

  get protocolVersion(): string {
    return this.negotiatedVersion ?? "";
  }

  get now(): () => number {
    return this.nowFn;
  }

  setSink(sink: ServerSink): void {
    this.sink = sink;
    this.flushQueue();
  }

  cancelRequest(id: string | number, reason?: string): void {
    const record = this.inflight.get(id);
    if (record === undefined) return;
    record.cancelled = true;
    record.controller.abort(reason);
  }

  async idle(): Promise<void> {
    while (this.inflight.size > 0) {
      const tasks = [...this.inflight.values()].map((r) => r.promise);
      await Promise.allSettled(tasks);
    }
    this.flushQueue();
  }

  close(): void {
    if (this.serverPhase === "closed") return;
    this.serverPhase = "closed";
    for (const record of this.inflight.values()) {
      record.cancelled = true;
      record.controller.abort("server closed");
    }
    if (!this.shutdownEmitted) {
      this.shutdownEmitted = true;
      this.enqueue(
        notification("notifications/message", {
          level: "info",
          logger: "shutdown",
          data: { message: "Server shutting down" },
        }),
      );
    }
    this.flushQueue();
  }

  emitResourceUpdated(uri: string): void {
    if (!this.subscriptions.has(uri)) return;
    this.enqueue(notification("notifications/resources/updated", { uri }));
    this.flushQueue();
  }

  handleInput(input: unknown): JsonRpcOutbound[] {
    if (this.serverPhase === "closed") return [];
    const decoded = decodeEnvelope(input);
    switch (decoded.kind) {
      case "invalid":
        return [failure(decoded.id, decoded.code, decoded.message, decoded.data)];
      case "batch":
        return [failure(decoded.id, INVALID_REQUEST, "Batch requests are not supported")];
      case "notification":
        this.handleNotification(decoded.msg);
        this.flushQueue();
        return [];
      case "request": {
        const msg = decoded.msg;
        if (this.inflight.has(msg.id)) {
          return [failure(msg.id, INVALID_REQUEST, "Duplicate request id", { method: msg.method })];
        }
        this.startRequest(msg);
        return [];
      }
      case "response":
        return [];
      case "ignore":
        return [];
    }
  }

  drainNotifications(): JsonRpcNotification[] {
    const out = this.queue;
    this.queue = [];
    return out;
  }

  private handleNotification(msg: JsonRpcNotification): void {
    switch (msg.method) {
      case "notifications/initialized":
        if (this.serverPhase !== "closed") {
          this.serverPhase = "ready";
        }
        return;
      case "notifications/cancelled": {
        const params = msg.params ?? {};
        const requestId = params["requestId"];
        const reason = params["reason"];
        if (!isStringId(requestId)) return;
        const record = this.inflight.get(requestId);
        if (record === undefined) return;
        record.cancelled = true;
        record.controller.abort(typeof reason === "string" ? reason : undefined);
        return;
      }
      case "notifications/progress":
        return;
      case "notifications/roots/list_changed":
        return;
      default:
        return;
    }
  }

  private startRequest(msg: JsonRpcRequest): void {
    const record: InFlight = {
      controller: new AbortController(),
      cancelled: false,
      lastProgress: Number.NEGATIVE_INFINITY,
      promise: Promise.resolve(),
    };
    this.inflight.set(msg.id, record);
    record.promise = this.execute(msg, record);
  }

  private async execute(msg: JsonRpcRequest, record: InFlight): Promise<void> {
    try {
      const out = await this.route(msg, record);
      this.deliver(record, out);
    } catch (err) {
      this.deliver(record, fromError(msg.id, err));
    } finally {
      this.inflight.delete(msg.id);
      this.flushQueue();
    }
  }

  private route(msg: JsonRpcRequest, record: InFlight): Promise<JsonRpcOutbound> {
    const params = msg.params ?? {};
    if (msg.method === "initialize") {
      return this.routeInitialize(msg, params);
    }
    if (msg.method === "ping") {
      return Promise.resolve(success(msg.id, {}));
    }
    if (this.serverPhase !== "ready") {
      return Promise.resolve(
        failure(msg.id, INVALID_REQUEST, "Server not initialized", { method: msg.method }),
      );
    }
    return this.routeReady(msg, params, record);
  }

  private async routeInitialize(
    msg: JsonRpcRequest,
    params: Record<string, unknown>,
  ): Promise<JsonRpcOutbound> {
    if (this.serverPhase !== "await-initialize") {
      throw invalidRequest("Server already initialized", { method: msg.method });
    }
    const requested = params["protocolVersion"];
    const supported: readonly string[] = SUPPORTED_PROTOCOL_VERSIONS;
    const version =
      typeof requested === "string" && supported.includes(requested)
        ? requested
        : LATEST_PROTOCOL_VERSION;
    this.negotiatedVersion = version;
    const caps = params["capabilities"];
    this.clientCapabilities = isRecord(caps) ? caps : {};
    this.serverPhase = "await-initialized";
    const result: Record<string, unknown> = {
      protocolVersion: version,
      capabilities: CAPABILITIES,
      serverInfo: this.serverInfo,
    };
    if (this.instructions.length > 0) result["instructions"] = this.instructions;
    return success(msg.id, result);
  }

  private async routeReady(
    msg: JsonRpcRequest,
    params: Record<string, unknown>,
    record: InFlight,
  ): Promise<JsonRpcOutbound> {
    const ctx = this.makeContext(record);
    switch (msg.method) {
      case "tools/list":
        return this.listResult(msg.id, "tools", this.registry.listTools(), params);
      case "tools/call":
        return await this.callTool(msg.id, params, ctx);
      case "resources/list":
        return this.listResult(msg.id, "resources", this.registry.listResources(), params);
      case "resources/templates/list":
        return this.listResult(
          msg.id,
          "resourceTemplates",
          this.registry.listResourceTemplates(),
          params,
        );
      case "resources/read":
        return await this.readResource(msg.id, params, ctx);
      case "resources/subscribe":
        return this.subscribe(msg.id, params);
      case "resources/unsubscribe":
        return this.unsubscribe(msg.id, params);
      case "prompts/list":
        return this.listResult(msg.id, "prompts", this.registry.listPrompts(), params);
      case "prompts/get":
        return await this.getPrompt(msg.id, params, ctx);
      case "completion/complete":
        return await this.complete(msg.id, params);
      case "logging/setLevel":
        return this.setLevel(msg.id, params);
      default:
        throw methodNotFound("Method not found", { method: msg.method });
    }
  }

  private listResult<T>(
    id: string | number,
    key: string,
    items: T[],
    params: Record<string, unknown>,
  ): JsonRpcOutbound {
    const paged = paginate(items, params["cursor"], this.pageSize);
    const result: Record<string, unknown> = {};
    result[key] = paged.page;
    if (paged.nextCursor !== undefined) result["nextCursor"] = paged.nextCursor;
    return success(id, result);
  }

  private async callTool(
    id: string | number,
    params: Record<string, unknown>,
    ctx: ServerContext,
  ): Promise<JsonRpcOutbound> {
    const name = params["name"];
    if (typeof name !== "string") {
      throw invalidParams("tools/call requires a string name", { reason: "missing name" });
    }
    const tool = this.registry.getTool(name);
    if (tool === undefined) {
      throw invalidParams("Unknown tool", { name });
    }
    let rawArgs: Record<string, unknown> = {};
    const argsIn = params["arguments"];
    if (argsIn !== undefined) {
      if (!isRecord(argsIn)) {
        throw invalidParams("tools/call arguments must be an object", { name });
      }
      rawArgs = argsIn;
    }
    const args = applyDefaults(tool.def.inputSchema, rawArgs);
    const errors = validateAgainstSchema(tool.def.inputSchema, args);
    if (errors.length > 0) {
      throw invalidParams("Invalid tool arguments", { errors });
    }

    let result: CallToolResult;
    try {
      result = await tool.handler(args, ctx);
    } catch (err) {
      if (err instanceof JsonRpcError && err.code === INVALID_PARAMS) throw err;
      const message = err instanceof Error ? err.message : String(err);
      return success(id, {
        content: [textBlock(`Tool execution failed: ${message}`)],
        isError: true,
      });
    }
    const call: CallToolResult = Array.isArray(result?.content)
      ? result
      : { content: [textBlock("Tool execution failed: handler returned a malformed result")], isError: true };

    const hasStructured = isRecord(call.structuredContent);
    if (tool.def.outputSchema !== undefined) {
      if (!call.isError) {
        if (!hasStructured) {
          return success(id, {
            content: [
              textBlock("Tool execution failed: outputSchema requires structuredContent"),
            ],
            isError: true,
          });
        }
        const outErrors = validateAgainstSchema(
          tool.def.outputSchema,
          call.structuredContent,
        );
        if (outErrors.length > 0) {
          return success(id, {
            ...call,
            content: [
              ...call.content,
              textBlock(
                `Tool execution failed: structured content does not match outputSchema: ${JSON.stringify(outErrors)}`,
              ),
            ],
            isError: true,
          });
        }
      }
      if (hasStructured) {
        return success(id, {
          ...call,
          content: [...call.content, textBlock(JSON.stringify(call.structuredContent))],
        });
      }
    }
    return success(id, { ...call });
  }

  private async readResource(
    id: string | number,
    params: Record<string, unknown>,
    ctx: ServerContext,
  ): Promise<JsonRpcOutbound> {
    const uri = params["uri"];
    if (typeof uri !== "string") {
      throw invalidParams("resources/read requires a string uri", { reason: "missing uri" });
    }
    const staticEntry = this.registry.getResource(uri);
    const templateEntry = staticEntry === undefined ? this.registry.matchTemplate(uri) : undefined;
    const handler = staticEntry?.handler ?? templateEntry?.handler;
    if (handler === undefined) {
      throw resourceNotFound("Unknown resource", { uri });
    }
    const raw: ResourceReadResult = await handler(uri, ctx);
    const contents = Array.isArray(raw?.contents) ? raw.contents : [];
    const normalized: Record<string, unknown>[] = [];
    for (const entry of contents) {
      if (!isRecord(entry) || typeof entry["uri"] !== "string" || typeof entry["text"] !== "string") {
        continue;
      }
      const out: Record<string, unknown> = { uri: entry["uri"], text: entry["text"] };
      if (typeof entry["mimeType"] === "string") out["mimeType"] = entry["mimeType"];
      normalized.push(out);
    }
    return success(id, { contents: normalized });
  }

  private subscribe(id: string | number, params: Record<string, unknown>): JsonRpcOutbound {
    const uri = params["uri"];
    if (typeof uri !== "string") {
      throw invalidParams("resources/subscribe requires a string uri", { reason: "missing uri" });
    }
    if (this.registry.getResource(uri) === undefined && this.registry.matchTemplate(uri) === undefined) {
      throw resourceNotFound("Unknown resource", { uri });
    }
    this.subscriptions.add(uri);
    return success(id, {});
  }

  private unsubscribe(id: string | number, params: Record<string, unknown>): JsonRpcOutbound {
    const uri = params["uri"];
    if (typeof uri === "string") this.subscriptions.delete(uri);
    return success(id, {});
  }

  private async getPrompt(
    id: string | number,
    params: Record<string, unknown>,
    ctx: ServerContext,
  ): Promise<JsonRpcOutbound> {
    const name = params["name"];
    if (typeof name !== "string") {
      throw invalidParams("prompts/get requires a string name", { reason: "missing name" });
    }
    const entry = this.registry.getPrompt(name);
    if (entry === undefined) {
      throw invalidParams("Unknown prompt", { name });
    }
    let argsIn: Record<string, unknown> = {};
    const argsParam = params["arguments"];
    if (argsParam !== undefined) {
      if (!isRecord(argsParam)) {
        throw invalidParams("prompts/get arguments must be an object", { name });
      }
      argsIn = argsParam;
    }
    const strArgs: Record<string, string> = {};
    for (const [k, v] of Object.entries(argsIn)) {
      if (typeof v !== "string") {
        throw invalidParams(`Prompt argument "${k}" must be a string`, { argument: k });
      }
      strArgs[k] = v;
    }
    for (const arg of entry.def.arguments ?? []) {
      if (arg.required === true && strArgs[arg.name] === undefined) {
        throw invalidParams(`Missing required argument: ${arg.name}`, { argument: arg.name });
      }
    }
    const result = await entry.handler(strArgs, ctx);
    const out: Record<string, unknown> = { messages: Array.isArray(result?.messages) ? result.messages : [] };
    if (typeof result?.description === "string") out["description"] = result.description;
    return success(id, out);
  }

  private async complete(id: string | number, params: Record<string, unknown>): Promise<JsonRpcOutbound> {
    const ref = params["ref"];
    const arg = params["argument"];
    if (!isRecord(ref) || !isRecord(arg)) {
      throw invalidParams("completion/complete requires ref and argument objects");
    }
    const refType = ref["type"];
    if (typeof refType !== "string" || (refType !== "ref/prompt" && refType !== "ref/resource")) {
      throw invalidParams("Unknown completion ref", { ref: ref["type"] });
    }
    const refName = ref["name"];
    if (typeof refName !== "string") {
      throw invalidParams("completion/complete ref.name must be a string");
    }
    const argName = arg["name"];
    const argValue = arg["value"];
    if (typeof argName !== "string" || typeof argValue !== "string") {
      throw invalidParams("completion/complete argument.name/value must be strings");
    }
    const handler = this.registry.getCompletion();
    if (handler === undefined) {
      throw invalidParams("Completions are not available");
    }
    const context: Record<string, string> = { refType, refName };
    const ctxIn = params["context"];
    if (isRecord(ctxIn)) {
      for (const [k, v] of Object.entries(ctxIn)) {
        if (typeof v === "string") context[k] = v;
      }
    }
    const values = await handler(argName, argValue, context);
    const completion: Record<string, unknown> = {
      values: Array.isArray(values?.values)
        ? values.values.filter((v): v is string => typeof v === "string")
        : [],
    };
    if (typeof values?.total === "number") completion["total"] = values.total;
    if (typeof values?.hasMore === "boolean") completion["hasMore"] = values.hasMore;
    return success(id, { completion });
  }

  private setLevel(id: string | number, params: Record<string, unknown>): JsonRpcOutbound {
    const level = params["level"];
    const levels = LOG_LEVELS as Partial<Record<LogLevel, number>>;
    if (typeof level !== "string" || levels[level as LogLevel] === undefined) {
      throw invalidParams("Invalid log level", { level: params["level"] });
    }
    this.currentLevel = level as LogLevel;
    return success(id, {});
  }

  private makeContext(record: InFlight): ServerContext {
    return {
      notify: (msg: JsonRpcNotification): void => {
        this.enqueue(msg);
      },
      progress: (token, progress, total, message): void => {
        if (token === undefined) return;
        if (progress <= record.lastProgress) return;
        record.lastProgress = progress;
        const params: Record<string, unknown> = { progressToken: token, progress };
        if (total !== undefined) params["total"] = total;
        if (message !== undefined) params["message"] = message;
        this.enqueue(notification("notifications/progress", params));
      },
      log: (level, logger, data): void => {
        if (LOG_LEVELS[level] < LOG_LEVELS[this.currentLevel]) return;
        this.enqueue(notification("notifications/message", { level, logger, data }));
      },
      signal: record.controller.signal,
      clientCapabilities: this.clientCapabilities,
      cache: this.cache,
    };
  }

  private enqueue(msg: JsonRpcNotification): void {
    if (this.serverPhase === "closed") return;
    if (this.sink !== undefined) {
      this.sink.emit(msg);
      return;
    }
    this.queue.push(msg);
  }

  private flushQueue(): void {
    if (this.sink === undefined) return;
    const pending = this.queue;
    this.queue = [];
    for (const msg of pending) this.sink.emit(msg);
  }

  private deliver(record: InFlight, out: JsonRpcOutbound): void {
    // An aborted request MUST NOT produce a response.
    if (record.cancelled) return;
    if (this.sink !== undefined) {
      this.sink.emit(out);
      return;
    }
    if ("method" in out && typeof out.method === "string") {
      this.queue.push(out);
    }
  }
}
