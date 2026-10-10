import type { ResponseCache } from "../net/cache.js";
import { Dispatcher } from "./dispatch.js";
import type { ServerPhase, ServerSink } from "./dispatch.js";
import type { Registry } from "./registry.js";
import type {
  Implementation,
  JsonRpcNotification,
  JsonRpcOutbound,
  RequestId,
} from "./types.js";

export type { ServerPhase, ServerSink };

export interface ServerOptions {
  registry: Registry;
  cache: ResponseCache;
  serverInfo: Implementation;
  instructions: string;
  pageSize?: number;
  now?: () => number;
  sink?: ServerSink;
}

export class McpServer {
  private readonly dispatcher: Dispatcher;

  constructor(opts: ServerOptions) {
    this.dispatcher = new Dispatcher(opts);
  }

  handleInput(input: unknown): JsonRpcOutbound[] {
    return this.dispatcher.handleInput(input);
  }

  drainNotifications(): JsonRpcNotification[] {
    return this.dispatcher.drainNotifications();
  }

  setSink(sink: ServerSink): void {
    this.dispatcher.setSink(sink);
  }

  cancelRequest(id: RequestId, reason?: string): void {
    this.dispatcher.cancelRequest(id, reason);
  }

  idle(): Promise<void> {
    return this.dispatcher.idle();
  }

  close(): void {
    this.dispatcher.close();
  }

  notifyResourceUpdated(uri: string): void {
    this.dispatcher.emitResourceUpdated(uri);
  }

  get phase(): ServerPhase {
    return this.dispatcher.phase;
  }

  get isReady(): boolean {
    return this.dispatcher.isReady;
  }

  get protocolVersion(): string {
    return this.dispatcher.protocolVersion;
  }
}
