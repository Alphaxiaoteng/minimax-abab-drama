import type {
  CallToolResult,
  CompletionValues,
  GetPromptResult,
  PromptDefinition,
  ResourceDefinition,
  ResourceReadResult,
  ResourceTemplateDefinition,
  ServerContext,
  ToolDefinition,
} from "./types.js";

export interface ToolHandler {
  (args: Record<string, unknown>, ctx: ServerContext): Promise<CallToolResult>;
}
export interface ResourceHandler {
  (uri: string, ctx: ServerContext): Promise<ResourceReadResult>;
}
export interface PromptHandler {
  (args: Record<string, string>, ctx: ServerContext): Promise<GetPromptResult>;
}
export interface CompletionHandler {
  (argName: string, value: string, context: Record<string, string>): Promise<CompletionValues>;
}

interface TemplateEntry {
  def: ResourceTemplateDefinition;
  handler: ResourceHandler;
  match: (uri: string) => Record<string, string> | undefined;
}

const PLACEHOLDER = /^\{([A-Za-z_][A-Za-z0-9_]*)\}$/;

export type UriMatcher = (uri: string) => Record<string, string> | undefined;

/**
 * Compiles an RFC 6570-ish `{name}` template into a matcher. A repeated placeholder name is
 * permitted, but two segments capturing the same name with different values reject the URI.
 */
export function compileTemplate(uriTemplate: string): UriMatcher {
  const segments = uriTemplate.split("/");
  const parsed: { literal?: string; name?: string }[] = segments.map((seg) => {
    const m = PLACEHOLDER.exec(seg);
    if (m && m[1] !== undefined) return { name: m[1] };
    if (seg.startsWith("{") || seg.endsWith("}")) {
      throw new Error(`Invalid template placeholder in uriTemplate: "${uriTemplate}"`);
    }
    return { literal: seg };
  });

  return (uri: string): Record<string, string> | undefined => {
    const parts = uri.split("/");
    if (parts.length !== parsed.length) return undefined;
    const out: Record<string, string> = {};
    for (const [i, seg] of parsed.entries()) {
      const part = parts[i];
      if (part === undefined) return undefined;
      if (seg.literal !== undefined) {
        if (part !== seg.literal) return undefined;
        continue;
      }
      const name = seg.name;
      if (name === undefined || part.length === 0) return undefined;
      const prior = out[name];
      if (prior !== undefined && prior !== part) return undefined;
      out[name] = part;
    }
    return out;
  };
}

export class Registry {
  private readonly tools = new Map<string, { def: ToolDefinition; handler: ToolHandler }>();
  private readonly resources = new Map<string, { def: ResourceDefinition; handler: ResourceHandler }>();
  private readonly templates: TemplateEntry[] = [];
  private readonly prompts = new Map<string, { def: PromptDefinition; handler: PromptHandler }>();
  private completion: CompletionHandler | undefined;

  registerTool(def: ToolDefinition, handler: ToolHandler): void {
    if (this.tools.has(def.name)) {
      throw new Error(`Duplicate tool registration: "${def.name}"`);
    }
    this.tools.set(def.name, { def, handler });
  }

  registerResource(def: ResourceDefinition, handler: ResourceHandler): void {
    if (this.resources.has(def.uri)) {
      throw new Error(`Duplicate resource registration: "${def.uri}"`);
    }
    this.resources.set(def.uri, { def, handler });
  }

  registerResourceTemplate(def: ResourceTemplateDefinition, handler: ResourceHandler): void {
    if (this.templates.some((t) => t.def.uriTemplate === def.uriTemplate)) {
      throw new Error(`Duplicate resource template registration: "${def.uriTemplate}"`);
    }
    this.templates.push({ def, handler, match: compileTemplate(def.uriTemplate) });
  }

  registerPrompt(def: PromptDefinition, handler: PromptHandler): void {
    if (this.prompts.has(def.name)) {
      throw new Error(`Duplicate prompt registration: "${def.name}"`);
    }
    this.prompts.set(def.name, { def, handler });
  }

  setCompletions(handler: CompletionHandler): void {
    this.completion = handler;
  }

  hasCompletions(): boolean {
    return this.completion !== undefined;
  }

  listTools(): ToolDefinition[] {
    return [...this.tools.values()].map((entry) => entry.def);
  }

  listResources(): ResourceDefinition[] {
    return [...this.resources.values()].map((entry) => entry.def);
  }

  listResourceTemplates(): ResourceTemplateDefinition[] {
    return this.templates.map((entry) => entry.def);
  }

  listPrompts(): PromptDefinition[] {
    return [...this.prompts.values()].map((entry) => entry.def);
  }

  getTool(name: string): { def: ToolDefinition; handler: ToolHandler } | undefined {
    return this.tools.get(name);
  }

  getResource(uri: string): { def: ResourceDefinition; handler: ResourceHandler } | undefined {
    return this.resources.get(uri);
  }

  getPrompt(name: string): { def: PromptDefinition; handler: PromptHandler } | undefined {
    return this.prompts.get(name);
  }

  matchTemplate(uri: string): { def: ResourceTemplateDefinition; handler: ResourceHandler } | undefined {
    for (const entry of this.templates) {
      if (entry.match(uri) !== undefined) {
        return { def: entry.def, handler: entry.handler };
      }
    }
    return undefined;
  }

  matchTemplateWithParams(uri: string): {
    def: ResourceTemplateDefinition;
    handler: ResourceHandler;
    params: Record<string, string>;
  } | undefined {
    for (const entry of this.templates) {
      const params = entry.match(uri);
      if (params !== undefined) {
        return { def: entry.def, handler: entry.handler, params };
      }
    }
    return undefined;
  }

  getCompletion(): CompletionHandler | undefined {
    return this.completion;
  }
}
