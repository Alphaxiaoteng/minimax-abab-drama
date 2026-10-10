import type { ResponseCache } from "../net/cache.js";

export type RequestId = string | number;

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: RequestId;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcSuccess {
  jsonrpc: "2.0";
  id: RequestId;
  result: Record<string, unknown>;
}

export interface JsonRpcFailure {
  jsonrpc: "2.0";
  id: RequestId;
  error: { code: number; message: string; data?: unknown };
}

export type JsonRpcMessage =
  | JsonRpcRequest
  | JsonRpcNotification
  | JsonRpcSuccess
  | JsonRpcFailure;

export type JsonRpcOutbound =
  | JsonRpcSuccess
  | JsonRpcFailure
  | JsonRpcNotification;

export interface Implementation {
  name: string;
  title?: string;
  version: string;
}

export interface ToolAnnotations {
  title?: string;
  readOnlyHint?: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
  openWorldHint?: boolean;
}

export interface ToolDefinition {
  name: string;
  title?: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  annotations?: ToolAnnotations;
}

export interface CallToolResult {
  content: ContentBlock[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
}

export interface ResourceDefinition {
  uri: string;
  name: string;
  title?: string;
  description?: string;
  mimeType?: string;
  size?: number;
  annotations?: Annotations;
}

export interface ResourceTemplateDefinition {
  uriTemplate: string;
  name: string;
  title?: string;
  description?: string;
  mimeType?: string;
  annotations?: Annotations;
}

export interface ResourceReadResult {
  contents: { uri: string; mimeType?: string; text: string }[];
}

export interface PromptArgument {
  name: string;
  title?: string;
  description?: string;
  required?: boolean;
}

export interface PromptDefinition {
  name: string;
  title?: string;
  description?: string;
  arguments?: PromptArgument[];
}

export interface PromptMessage {
  role: "user" | "assistant";
  content: TextContent | EmbeddedResource;
}

export interface GetPromptResult {
  description?: string;
  messages: PromptMessage[];
}

export interface CompletionValues {
  values: string[];
  total?: number;
  hasMore?: boolean;
}

export interface CompleteResult {
  completion: CompletionValues;
}

export type LogLevel =
  | "debug"
  | "info"
  | "notice"
  | "warning"
  | "error"
  | "critical"
  | "alert"
  | "emergency";

export interface ServerCapabilities {
  tools?: { listChanged?: boolean };
  resources?: { subscribe?: boolean; listChanged?: boolean };
  prompts?: { listChanged?: boolean };
  logging?: Record<string, never>;
  completions?: Record<string, never>;
}

export interface InitializeResult {
  protocolVersion: string;
  capabilities: ServerCapabilities;
  serverInfo: Implementation;
  instructions?: string;
}

export interface Annotations {
  audience?: ("user" | "assistant")[];
  priority?: number;
  lastModified?: string;
}

export type TextContent = { type: "text"; text: string; annotations?: Annotations };
export type ResourceLink = {
  type: "resource_link";
  uri: string;
  name: string;
  title?: string;
  description?: string;
  mimeType?: string;
  annotations?: Annotations;
};
export type EmbeddedResource = { type: "resource"; resource: TextResourceContents };
export type TextResourceContents = { uri: string; mimeType?: string; text: string };
export type ContentBlock = TextContent | ResourceLink | EmbeddedResource;

export interface ServerContext {
  notify(msg: JsonRpcNotification): void;
  progress(
    token: string | number | undefined,
    progress: number,
    total?: number,
    message?: string,
  ): void;
  log(level: LogLevel, logger: string, data: unknown): void;
  signal: AbortSignal;
  clientCapabilities: Record<string, unknown>;
  cache: ResponseCache;
}

export const LATEST_PROTOCOL_VERSION = "2025-06-18";
export const SUPPORTED_PROTOCOL_VERSIONS = [
  "2025-06-18",
  "2025-03-26",
  "2024-11-05",
] as const;
