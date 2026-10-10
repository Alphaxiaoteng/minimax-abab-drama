import type { ResourceDefinition, ResourceReadResult, ResourceTemplateDefinition } from "../protocol/types.js";
import type { ResourceDeps } from "../tools/deps.js";

export const CATALOG_RESOURCE: ResourceDefinition = {
  uri: "netintel://catalog",
  name: "NetIntel Sources Catalog",
  title: "Intelligence Catalog",
  description: "Live overview of open-source intelligence feeds and cache status.",
  mimeType: "application/json",
};

export const FEED_TEMPLATE: ResourceTemplateDefinition = {
  uriTemplate: "netintel://feed/{key}",
  name: "Dynamic Topic Feed",
  title: "Feed by Cache Key",
  description: "Cached topic stream or digest by key.",
  mimeType: "application/json",
};

export function registerResources(
  registry: {
    registerResource: (def: ResourceDefinition, handler: (uri: string) => Promise<ResourceReadResult>) => void;
    registerResourceTemplate: (def: ResourceTemplateDefinition, handler: (uri: string) => Promise<ResourceReadResult>) => void;
  },
  deps: ResourceDeps,
): void {
  registry.registerResource(CATALOG_RESOURCE, async (uri) => {
    const catalog = {
      uri,
      offline: deps.offline,
      sources: deps.sources.map((s) => ({
        id: s.id,
        label: s.label,
        homepage: s.homepage,
      })),
      cache: deps.cache.stats(),
      subscriptions: deps.subscriptions.list(),
    };

    return {
      contents: [
        {
          uri,
          mimeType: "application/json",
          text: JSON.stringify(catalog, null, 2),
        },
      ],
    };
  });

  registry.registerResourceTemplate(FEED_TEMPLATE, async (uri) => {
    const match = uri.match(/^netintel:\/\/feed\/(.+)$/);
    const key = match ? match[1] : uri;
    const cached = key ? deps.cache.get(key) : undefined;

    let text: string;
    let mimeType = "application/json";

    if (typeof cached === "string") {
      text = cached;
      if (text.startsWith("#")) mimeType = "text/markdown";
    } else if (cached !== undefined) {
      text = JSON.stringify(cached, null, 2);
    } else {
      text = JSON.stringify({ key, error: "Feed not found or expired", available: false });
    }

    return {
      contents: [
        {
          uri,
          mimeType,
          text,
        },
      ],
    };
  });
}
