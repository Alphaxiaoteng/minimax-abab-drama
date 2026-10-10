import type { GetPromptResult, PromptDefinition } from "../protocol/types.js";
import type { PromptDeps } from "../tools/deps.js";

export const BRIEF_TOPIC_PROMPT: PromptDefinition = {
  name: "brief_topic",
  title: "Generate Topic Brief",
  description: "Prompt template guiding the LLM to research and summarize technical discussions across HN, GitHub, and arXiv.",
  arguments: [
    {
      name: "topic",
      title: "Target Topic",
      description: "Technology, library, or architecture name (e.g. MCP, WebAssembly, KV-Cache)",
      required: true,
    },
  ],
};

export function registerPrompts(
  registry: {
    registerPrompt: (def: PromptDefinition, handler: (args: Record<string, string>) => Promise<GetPromptResult>) => void;
  },
  _deps: PromptDeps,
): void {
  registry.registerPrompt(BRIEF_TOPIC_PROMPT, async (args) => {
    const topic = args["topic"] ?? "Model Context Protocol";

    return {
      description: `Executive brief research instructions for ${topic}`,
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Executive brief for "${topic}". Use net_search to gather Hacker News discussions, GitHub repositories, and arXiv papers, then produce a technical brief.`,
          },
        },
      ],
    };
  });
}
