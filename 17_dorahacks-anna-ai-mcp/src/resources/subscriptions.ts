/**
 * Tracks client resource subscriptions. Keys are used verbatim as the last
 * segment of `netintel://feed/{key}` (no URL-encoding) so the tool-side cache
 * touch and the resource-side read always agree on the exact string.
 */
const FEED_PREFIX = "netintel://feed/";

export class SubscriptionHub {
  private readonly uris = new Set<string>();

  subscribe(uri: string): void {
    this.uris.add(uri);
  }

  unsubscribe(uri: string): void {
    this.uris.delete(uri);
  }

  /** deterministic, sorted view for completion + introspection */
  list(): string[] {
    return [...this.uris].sort();
  }

  has(uri: string): boolean {
    return this.uris.has(uri);
  }

  /** the subscribed feed URIs invalidated by a touched cache key */
  notifyCacheKey(key: string): { uri: string }[] {
    const uri = `${FEED_PREFIX}${key}`;
    return this.uris.has(uri) ? [{ uri }] : [];
  }
}
