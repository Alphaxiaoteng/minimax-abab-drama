import type { SourceAdapter } from "../types.js";
import { ArxivSourceAdapter } from "./arxiv.js";
import { GitHubSource } from "./github.js";
import { HackerNewsSource } from "./hackernews.js";
import type { SourceOptions } from "./shared.js";

export const SOURCE_IDS = ["hackernews", "github", "arxiv"] as const;
export type SourceId = (typeof SOURCE_IDS)[number];

export function createSources(opts: SourceOptions): SourceAdapter[] {
  return [
    new HackerNewsSource(opts),
    new GitHubSource(opts),
    new ArxivSourceAdapter(opts),
  ];
}

export { ArxivSourceAdapter, GitHubSource, HackerNewsSource };
export { ArxivSourceAdapter as ArxivSource, GitHubSource as GitHubSourceAdapter, HackerNewsSource as HackerNewsSourceAdapter };
export type { SourceOptions } from "./shared.js";
