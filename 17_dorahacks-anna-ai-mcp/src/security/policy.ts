// MCP Security Policy Guard - Enterprise-grade sandbox enforcement
// Zero-dependency implementation with strict access control

export interface SecurityPolicy {
  readonlyMode: boolean;
  enabled: boolean;
  allowedTools?: string[];
  blockedTools?: string[];
  originWhitelist?: string[];
  rateLimitPerMinute?: number;
  maxResponseSize?: number;
}

export const DEFAULT_POLICY: SecurityPolicy = {
  readonlyMode: false,
  enabled: true,
  blockedTools: [],
  originWhitelist: ['http://localhost:*', 'http://127.0.0.1:*', 'vscode-webview://*'],
  rateLimitPerMinute: 60,
  maxResponseSize: 1_048_576, // 1MB
};

export class SecurityPolicyGuard {
  private policy: SecurityPolicy;
  private requestTimestamps: Map<string, number[]>;

  constructor(policy: Partial<SecurityPolicy> = {}) {
    this.policy = { ...DEFAULT_POLICY, ...policy };
    this.requestTimestamps = new Map();
  }

  setPolicy(partial: Partial<SecurityPolicy>): void {
    Object.assign(this.policy, partial);
  }

  getPolicy(): SecurityPolicy {
    return { ...this.policy };
  }

  checkToolAccess(toolName: string): { allowed: boolean; reason?: string } {
    if (!this.policy.enabled) return { allowed: true };

    // Check explicit blocklist
    if (this.policy.blockedTools?.includes(toolName)) {
      return { allowed: false, reason: `Tool ${toolName} is explicitly blocked by security policy` };
    }

    // Check read-only mode
    if (this.policy.readonlyMode) {
      const writeTools = ['net_fetch', 'net_cache', 'net_digest'];
      if (writeTools.includes(toolName)) {
        return { allowed: false, reason: `Tool ${toolName} is blocked in read-only mode` };
      }
    }

    return { allowed: true };
  }

  checkOrigin(origin: string): { allowed: boolean; reason?: string } {
    if (!this.policy.originWhitelist || this.policy.originWhitelist.length === 0) {
      return { allowed: true };
    }

    for (const pattern of this.policy.originWhitelist) {
      if (this.matchOrigin(origin, pattern)) {
        return { allowed: true };
      }
    }

    return {
      allowed: false,
      reason: `Origin ${origin} not in whitelist`,
    };
  }

  checkRateLimit(clientId: string): { allowed: boolean; retryAfter?: number } {
    const now = Date.now();
    const windowMs = 60_000; // 1 minute sliding window
    const limit = this.policy.rateLimitPerMinute ?? 60;

    let timestamps = this.requestTimestamps.get(clientId) || [];
    timestamps = timestamps.filter((ts) => now - ts < windowMs);

    if (timestamps.length >= limit) {
      const oldest = timestamps[0] ?? now;
      const retryAfter = Math.ceil((oldest + windowMs - now) / 1000);
      return { allowed: false, retryAfter };
    }

    timestamps.push(now);
    this.requestTimestamps.set(clientId, timestamps);

    return { allowed: true };
  }

  checkResponseSize(size: number): { allowed: boolean; reason?: string } {
    const maxSize = this.policy.maxResponseSize ?? 1_048_576;
    if (size > maxSize) {
      return {
        allowed: false,
        reason: `Response size ${size} exceeds maximum allowed ${maxSize}`,
      };
    }
    return { allowed: true };
  }

  private matchOrigin(origin: string, pattern: string): boolean {
    // Simple wildcard matching: http://localhost:* matches any port
    if (pattern.endsWith(':*')) {
      const prefix = pattern.slice(0, -2);
      return origin.startsWith(prefix);
    }
    return origin === pattern;
  }
}

// Singleton instance for global access
export const globalPolicyGuard = new SecurityPolicyGuard();
