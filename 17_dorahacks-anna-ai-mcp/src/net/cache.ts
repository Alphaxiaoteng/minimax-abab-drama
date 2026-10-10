const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;
const MASK64 = 0xffffffffffffffffn;
const KEY_SEP = "\u001f";
const DEFAULT_TTL_MS = 300_000;
const DEFAULT_MAX_ENTRIES = 256;

export interface CacheStats {
  hits: number;
  misses: number;
  sets: number;
  entries: number;
}

interface CacheEntry {
  value: unknown;
  expiresAt: number;
}

export class ResponseCache {
  private readonly store = new Map<string, CacheEntry>();
  private readonly ttlMs: number;
  private readonly maxEntries: number;
  private readonly now: () => number;
  private hits = 0;
  private misses = 0;
  private sets = 0;

  constructor(opts?: { ttlMs?: number; maxEntries?: number; now?: () => number }) {
    this.ttlMs = opts?.ttlMs ?? DEFAULT_TTL_MS;
    this.maxEntries = opts?.maxEntries ?? DEFAULT_MAX_ENTRIES;
    this.now = opts?.now ?? Date.now;
  }

  get(key: string): unknown | undefined {
    const entry = this.store.get(key);
    if (entry === undefined) {
      this.misses += 1;
      return undefined;
    }
    if (entry.expiresAt <= this.now()) {
      this.store.delete(key);
      this.misses += 1;
      return undefined;
    }
    this.store.delete(key);
    this.store.set(key, entry);
    this.hits += 1;
    return entry.value;
  }

  set(key: string, value: unknown): void {
    if (this.store.has(key)) {
      this.store.delete(key);
    }
    this.store.set(key, { value, expiresAt: this.now() + this.ttlMs });
    this.sets += 1;
    while (this.store.size > this.maxEntries) {
      const oldest = this.store.keys().next();
      if (oldest.done === true) {
        break;
      }
      this.store.delete(oldest.value);
    }
  }

  has(key: string): boolean {
    const entry = this.store.get(key);
    if (entry === undefined) {
      return false;
    }
    if (entry.expiresAt <= this.now()) {
      this.store.delete(key);
      return false;
    }
    return true;
  }

  clear(): void {
    this.store.clear();
  }

  keys(): string[] {
    return [...this.store.keys()].reverse();
  }

  stats(): CacheStats {
    return {
      hits: this.hits,
      misses: this.misses,
      sets: this.sets,
      entries: this.store.size,
    };
  }

  static key(parts: (string | number | undefined)[]): string {
    const joined = parts.map((p) => (p === undefined ? "" : String(p))).join(KEY_SEP);
    const bytes = new TextEncoder().encode(joined);
    let h = FNV_OFFSET;
    for (const b of bytes) {
      h = (h ^ BigInt(b)) * FNV_PRIME;
      h &= MASK64;
    }
    const prefix = parts[0] ?? "";
    return prefix + "|" + h.toString(16).padStart(16, "0");
  }
}
