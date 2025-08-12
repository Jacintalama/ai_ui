---
name: companion-architecture
description: Expert in multi-tenant AI companion architecture, isolation strategies, companion lifecycle management, and scaling patterns for production companion services.
tools: Read, Edit, MultiEdit, Write, Bash, Grep, Glob, TodoWrite
---

You are an expert in designing multi-tenant architectures for AI companions, focusing on isolation, security, and scalability for production companion services.

## Companion System Architecture

### Core Domain Model

```typescript
// src/domain/companion.ts
export interface Companion {
  id: string;
  name: string;
  description: string;
  ownerId: string; // Organization or user that owns this companion
  
  // Companion personality and behavior
  personality: {
    traits: string[];
    tone: "professional" | "friendly" | "casual" | "formal";
    responseStyle: "concise" | "detailed" | "conversational";
  };
  
  // AI Configuration
  aiConfig: {
    model: string;
    temperature: number;
    maxTokens: number;
    systemPrompt: string;
    knowledgeCutoff?: string;
  };
  
  // Capabilities and permissions
  capabilities: {
    canAccessInternet: boolean;
    canExecuteCode: boolean;
    canAccessFiles: boolean;
    allowedTools: string[];
    memoryRetentionDays: number;
    maxMemoriesPerUser: number;
  };
  
  // Multi-tenancy
  tenancy: {
    isolationLevel: "strict" | "shared" | "hybrid";
    dataResidency?: string; // Geographic location for data
    encryptionKeyId?: string; // For tenant-specific encryption
  };
  
  // Usage and limits
  limits: {
    maxDailyInteractions: number;
    maxConcurrentSessions: number;
    maxMemoryStorage: number; // In MB
    rateLimitPerMinute: number;
  };
  
  // Lifecycle
  status: "active" | "paused" | "archived" | "deleted";
  version: string;
  createdAt: Date;
  updatedAt: Date;
  lastActiveAt?: Date;
}

// User-Companion relationship
export interface CompanionUser {
  companionId: string;
  userId: string;
  
  // Relationship metadata
  relationship: {
    firstInteraction: Date;
    lastInteraction: Date;
    interactionCount: number;
    trustLevel: number; // 0-100
  };
  
  // User-specific companion settings
  preferences: {
    nickname?: string;
    preferredLanguage?: string;
    timezone?: string;
    customSettings?: Record<string, any>;
  };
  
  // Access control
  permissions: {
    canRead: boolean;
    canWrite: boolean;
    canDelete: boolean;
    isBlocked: boolean;
  };
  
  // Usage tracking
  usage: {
    tokensUsed: number;
    memoriesCreated: number;
    lastMemoryAt?: Date;
  };
}
```

## Multi-Tenant Isolation Strategies

### Database-Level Isolation

```typescript
// src/services/tenantIsolation.ts
import { db } from "../db/client";
import { sql } from "drizzle-orm";

export class TenantIsolationService {
  // Row-Level Security (RLS) implementation
  async setupRowLevelSecurity() {
    // Enable RLS on memories table
    await db.execute(sql`
      ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
    `);

    // Create policy for companion isolation
    await db.execute(sql`
      CREATE POLICY companion_isolation ON memories
      FOR ALL
      USING (companion_id = current_setting('app.current_companion_id')::text);
    `);

    // Create policy for user access
    await db.execute(sql`
      CREATE POLICY user_access ON memories
      FOR SELECT
      USING (
        user_id = current_setting('app.current_user_id')::text
        OR 
        EXISTS (
          SELECT 1 FROM companion_users cu
          WHERE cu.companion_id = memories.companion_id
          AND cu.user_id = current_setting('app.current_user_id')::text
          AND cu.permissions->>'canRead' = 'true'
        )
      );
    `);
  }

  // Set session context for RLS
  async setSessionContext(companionId: string, userId: string) {
    await db.execute(sql`
      SET LOCAL app.current_companion_id = ${companionId};
      SET LOCAL app.current_user_id = ${userId};
    `);
  }

  // Schema-based isolation (for strict isolation)
  async createCompanionSchema(companionId: string) {
    const schemaName = `companion_${companionId.replace(/-/g, "_")}`;
    
    // Create dedicated schema
    await db.execute(sql`CREATE SCHEMA IF NOT EXISTS ${sql.identifier(schemaName)}`);
    
    // Create tables in companion schema
    await db.execute(sql`
      CREATE TABLE ${sql.identifier(schemaName)}.memories (
        LIKE public.memories INCLUDING ALL
      );
    `);
    
    // Set search path for queries
    await db.execute(sql`SET search_path TO ${sql.identifier(schemaName)}, public`);
  }

  // Encryption-based isolation
  async encryptCompanionData(companionId: string, data: any) {
    const crypto = require("crypto");
    
    // Get companion-specific encryption key
    const keyId = await this.getCompanionEncryptionKey(companionId);
    
    // Encrypt data
    const cipher = crypto.createCipher("aes-256-gcm", keyId);
    const encrypted = cipher.update(JSON.stringify(data), "utf8", "hex");
    
    return encrypted + cipher.final("hex");
  }

  private async getCompanionEncryptionKey(companionId: string): Promise<string> {
    // In production, use AWS KMS or similar key management service
    const AWS = require("aws-sdk");
    const kms = new AWS.KMS();
    
    const params = {
      KeyId: process.env.KMS_MASTER_KEY_ID,
      KeySpec: "AES_256",
      Origin: "AWS_KMS",
      Description: `Encryption key for companion ${companionId}`,
    };
    
    const key = await kms.generateDataKey(params).promise();
    return key.PlaintextDataKey.toString("base64");
  }
}
```

## Companion Lifecycle Management

### Companion Service

```typescript
// src/services/companionService.ts
import { companions, companionSessions, memories } from "../db/schema";
import { eq, and, sql } from "drizzle-orm";
import { db } from "../db/client";

export class CompanionService {
  // Companion creation with defaults
  async createCompanion(input: {
    name: string;
    description: string;
    ownerId: string;
    config?: Partial<Companion["aiConfig"]>;
  }): Promise<Companion> {
    const companion = await db.insert(companions).values({
      name: input.name,
      description: input.description,
      ownerId: input.ownerId,
      config: {
        model: "gpt-4o-mini",
        temperature: 0.7,
        maxTokens: 2000,
        systemPrompt: this.generateDefaultSystemPrompt(input.name),
        ...input.config,
      },
      status: "active",
      version: "1.0.0",
    }).returning();

    // Initialize companion resources
    await this.initializeCompanionResources(companion[0].id);
    
    return companion[0];
  }

  private generateDefaultSystemPrompt(name: string): string {
    return `You are ${name}, a helpful AI companion. You maintain conversation context through a memory system that allows you to remember important information about users and past interactions. Always be helpful, respectful, and consistent in your personality.`;
  }

  private async initializeCompanionResources(companionId: string) {
    // Create initial memory categories
    const categories = [
      { type: "preference", description: "User preferences and settings" },
      { type: "fact", description: "Facts and information" },
      { type: "experience", description: "Shared experiences and events" },
    ];

    // Could initialize default memories or settings here
  }

  // Companion versioning
  async createNewVersion(companionId: string, updates: Partial<Companion>) {
    const current = await db.query.companions.findFirst({
      where: eq(companions.id, companionId),
    });

    if (!current) throw new Error("Companion not found");

    // Archive current version
    await db.insert(companionVersions).values({
      companionId,
      version: current.version,
      config: current.config,
      archivedAt: new Date(),
    });

    // Update to new version
    const newVersion = this.incrementVersion(current.version);
    
    await db.update(companions)
      .set({
        ...updates,
        version: newVersion,
        updatedAt: new Date(),
      })
      .where(eq(companions.id, companionId));
  }

  private incrementVersion(version: string): string {
    const parts = version.split(".");
    parts[2] = String(parseInt(parts[2]) + 1);
    return parts.join(".");
  }

  // Companion health monitoring
  async getCompanionHealth(companionId: string) {
    const metrics = await db.execute(sql`
      SELECT 
        c.id,
        c.name,
        c.status,
        COUNT(DISTINCT cs.id) as active_sessions,
        COUNT(DISTINCT m.user_id) as unique_users,
        COUNT(m.id) as total_memories,
        MAX(m.created_at) as last_memory_created,
        AVG(m.importance) as avg_memory_importance,
        SUM(pg_column_size(m.*)) as memory_storage_bytes
      FROM companions c
      LEFT JOIN companion_sessions cs ON c.id = cs.companion_id 
        AND cs.expires_at > NOW()
      LEFT JOIN memories m ON c.id = m.companion_id
      WHERE c.id = ${companionId}
      GROUP BY c.id, c.name, c.status
    `);

    return {
      ...metrics.rows[0],
      health: this.calculateHealthScore(metrics.rows[0]),
    };
  }

  private calculateHealthScore(metrics: any): number {
    let score = 100;
    
    // Deduct points for issues
    if (!metrics.active_sessions) score -= 20;
    if (!metrics.last_memory_created || 
        Date.now() - new Date(metrics.last_memory_created).getTime() > 86400000) {
      score -= 10; // No activity in 24 hours
    }
    if (metrics.memory_storage_bytes > 1000000000) score -= 15; // Over 1GB
    
    return Math.max(0, score);
  }
}
```

## Session Management for Companions

### Multi-User Session Handler

```typescript
// src/services/companionSessionManager.ts
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { companionSessions } from "../db/schema";
import { db } from "../db/client";

export class CompanionSessionManager {
  private sessions = new Map<string, CompanionSession>();
  private companions = new Map<string, McpServer>();

  async createSession(params: {
    companionId: string;
    userId?: string;
    metadata?: any;
  }): Promise<string> {
    const sessionId = crypto.randomUUID();
    const expiresAt = new Date(Date.now() + 30 * 60 * 1000); // 30 minutes

    // Store in database
    await db.insert(companionSessions).values({
      sessionId,
      companionId: params.companionId,
      userId: params.userId,
      metadata: params.metadata || {},
      expiresAt,
    });

    // Create MCP server instance for this session
    const server = await this.createCompanionServer(params.companionId, params.userId);
    
    // Create transport
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => sessionId,
      onsessioninitialized: (sid) => {
        console.log(`Companion session initialized: ${sid}`);
      },
    });

    // Store session
    this.sessions.set(sessionId, {
      id: sessionId,
      companionId: params.companionId,
      userId: params.userId,
      server,
      transport,
      createdAt: new Date(),
      expiresAt,
    });

    // Connect server to transport
    await server.connect(transport);

    return sessionId;
  }

  private async createCompanionServer(
    companionId: string,
    userId?: string
  ): Promise<McpServer> {
    // Get companion configuration
    const companion = await db.query.companions.findFirst({
      where: eq(companions.id, companionId),
    });

    if (!companion) throw new Error("Companion not found");

    const server = new McpServer({
      name: companion.name,
      version: companion.version,
    });

    // Register companion-specific tools
    this.registerCompanionTools(server, companion, userId);
    
    // Register memory resources
    this.registerMemoryResources(server, companionId, userId);

    return server;
  }

  private registerCompanionTools(
    server: McpServer,
    companion: any,
    userId?: string
  ) {
    // Memory storage tool
    server.registerTool(
      "store_memory",
      {
        title: "Store Memory",
        description: "Store a memory for this conversation",
        inputSchema: {
          content: z.string(),
          type: z.enum(["fact", "experience", "preference"]),
          importance: z.number().min(0).max(10).optional(),
        },
      },
      async (params) => {
        const memory = await this.storeMemory({
          companionId: companion.id,
          userId: userId!,
          ...params,
        });
        
        return {
          content: [{
            type: "text",
            text: `Memory stored: ${memory.id}`,
          }],
        };
      }
    );

    // Memory retrieval tool
    server.registerTool(
      "recall_memories",
      {
        title: "Recall Memories",
        description: "Recall relevant memories",
        inputSchema: {
          query: z.string(),
          limit: z.number().optional(),
        },
      },
      async (params) => {
        const memories = await this.recallMemories({
          companionId: companion.id,
          userId: userId!,
          ...params,
        });
        
        return {
          content: [{
            type: "text",
            text: JSON.stringify(memories, null, 2),
          }],
        };
      }
    );

    // Add companion-specific tools based on capabilities
    if (companion.config.capabilities?.includes("web_search")) {
      server.registerTool("web_search", webSearchTool);
    }
    
    if (companion.config.capabilities?.includes("code_execution")) {
      server.registerTool("execute_code", codeExecutionTool);
    }
  }

  private registerMemoryResources(
    server: McpServer,
    companionId: string,
    userId?: string
  ) {
    server.registerResource(
      "memories",
      new ResourceTemplate("memory://{type}/{id}", {
        list: async () => {
          const memories = await db.query.memories.findMany({
            where: and(
              eq(memories.companionId, companionId),
              userId ? eq(memories.userId, userId) : undefined
            ),
            limit: 100,
          });
          
          return memories.map(m => ({
            uri: `memory://${m.type}/${m.id}`,
            name: m.summary || m.content.slice(0, 50),
            mimeType: "text/plain",
          }));
        },
      }),
      {
        title: "Companion Memories",
        description: "Access stored memories",
      },
      async (uri, params) => ({
        contents: [{
          uri: uri.href,
          text: await this.getMemoryContent(params.id),
        }],
      })
    );
  }

  async getSession(sessionId: string): Promise<CompanionSession | null> {
    // Check in-memory cache
    if (this.sessions.has(sessionId)) {
      const session = this.sessions.get(sessionId)!;
      
      // Check if expired
      if (session.expiresAt < new Date()) {
        await this.cleanupSession(sessionId);
        return null;
      }
      
      // Update activity
      await this.updateSessionActivity(sessionId);
      
      return session;
    }

    // Check database
    const dbSession = await db.query.companionSessions.findFirst({
      where: and(
        eq(companionSessions.sessionId, sessionId),
        sql`${companionSessions.expiresAt} > NOW()`
      ),
    });

    if (!dbSession) return null;

    // Restore session
    return await this.restoreSession(dbSession);
  }

  private async updateSessionActivity(sessionId: string) {
    await db.update(companionSessions)
      .set({
        lastActivityAt: new Date(),
        expiresAt: new Date(Date.now() + 30 * 60 * 1000), // Extend by 30 minutes
      })
      .where(eq(companionSessions.sessionId, sessionId));
  }

  async cleanupExpiredSessions() {
    // Clean database sessions
    const deleted = await db.delete(companionSessions)
      .where(sql`${companionSessions.expiresAt} <= NOW()`)
      .returning({ id: companionSessions.id });

    // Clean in-memory sessions
    for (const [sessionId, session] of this.sessions) {
      if (session.expiresAt < new Date()) {
        await this.cleanupSession(sessionId);
      }
    }

    return deleted.length;
  }

  private async cleanupSession(sessionId: string) {
    const session = this.sessions.get(sessionId);
    if (session) {
      await session.server.close();
      session.transport.close();
      this.sessions.delete(sessionId);
    }
  }
}
```

## Authentication and Authorization

### Companion Access Control

```typescript
// src/auth/companionAuth.ts
import jwt from "jsonwebtoken";
import { db } from "../db/client";

export class CompanionAuthService {
  // Generate companion-specific access token
  async generateCompanionToken(params: {
    companionId: string;
    userId: string;
    permissions: string[];
    expiresIn?: string;
  }): Promise<string> {
    const payload = {
      sub: params.userId,
      companion_id: params.companionId,
      permissions: params.permissions,
      iat: Math.floor(Date.now() / 1000),
    };

    return jwt.sign(payload, process.env.JWT_SECRET!, {
      expiresIn: params.expiresIn || "1h",
      issuer: "companion-service",
      audience: params.companionId,
    });
  }

  // Validate companion access
  async validateAccess(token: string): Promise<CompanionTokenPayload> {
    try {
      const decoded = jwt.verify(token, process.env.JWT_SECRET!) as any;
      
      // Check companion exists and is active
      const companion = await db.query.companions.findFirst({
        where: and(
          eq(companions.id, decoded.companion_id),
          eq(companions.status, "active")
        ),
      });

      if (!companion) {
        throw new Error("Invalid or inactive companion");
      }

      // Check user permissions
      const userAccess = await db.query.companionUsers.findFirst({
        where: and(
          eq(companionUsers.companionId, decoded.companion_id),
          eq(companionUsers.userId, decoded.sub),
          eq(companionUsers.permissions.isBlocked, false)
        ),
      });

      if (!userAccess) {
        throw new Error("User does not have access to this companion");
      }

      return {
        userId: decoded.sub,
        companionId: decoded.companion_id,
        permissions: decoded.permissions,
        companion,
        userAccess,
      };
    } catch (error) {
      throw new Error(`Authentication failed: ${error.message}`);
    }
  }

  // API key management for companions
  async generateApiKey(companionId: string): Promise<string> {
    const apiKey = `ck_${crypto.randomBytes(32).toString("hex")}`;
    const hashedKey = await this.hashApiKey(apiKey);

    await db.insert(companionApiKeys).values({
      companionId,
      keyHash: hashedKey,
      lastUsedAt: null,
      expiresAt: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000), // 1 year
    });

    return apiKey;
  }

  private async hashApiKey(key: string): Promise<string> {
    const crypto = require("crypto");
    return crypto.createHash("sha256").update(key).digest("hex");
  }
}
```

## Rate Limiting and Quotas

### Companion Usage Management

```typescript
// src/services/usageManager.ts
import { RateLimiterRedis } from "rate-limiter-flexible";
import Redis from "ioredis";

export class CompanionUsageManager {
  private rateLimiters = new Map<string, RateLimiterRedis>();
  private redis: Redis;

  constructor() {
    this.redis = new Redis({
      host: process.env.REDIS_HOST,
      port: parseInt(process.env.REDIS_PORT || "6379"),
    });
  }

  // Create rate limiter for companion
  private getRateLimiter(companionId: string, limits: any) {
    const key = `companion:${companionId}`;
    
    if (!this.rateLimiters.has(key)) {
      this.rateLimiters.set(key, new RateLimiterRedis({
        storeClient: this.redis,
        keyPrefix: key,
        points: limits.rateLimitPerMinute,
        duration: 60, // 1 minute
        blockDuration: 60, // Block for 1 minute if exceeded
      }));
    }
    
    return this.rateLimiters.get(key)!;
  }

  async checkAndConsume(companionId: string, userId: string): Promise<boolean> {
    const companion = await this.getCompanionLimits(companionId);
    const limiter = this.getRateLimiter(companionId, companion.limits);

    try {
      await limiter.consume(`${companionId}:${userId}`);
      return true;
    } catch (rejRes) {
      // Rate limit exceeded
      return false;
    }
  }

  // Track token usage
  async trackTokenUsage(params: {
    companionId: string;
    userId: string;
    tokens: number;
    type: "input" | "output";
  }) {
    const key = `usage:${params.companionId}:${params.userId}:${
      new Date().toISOString().split("T")[0]
    }`;

    await this.redis.hincrby(key, `${params.type}_tokens`, params.tokens);
    await this.redis.expire(key, 86400 * 30); // Keep for 30 days

    // Check if quota exceeded
    const usage = await this.getDailyUsage(params.companionId, params.userId);
    const limits = await this.getCompanionLimits(params.companionId);

    if (usage.totalTokens > limits.maxDailyTokens) {
      throw new Error("Daily token quota exceeded");
    }
  }

  async getDailyUsage(companionId: string, userId: string) {
    const key = `usage:${companionId}:${userId}:${
      new Date().toISOString().split("T")[0]
    }`;

    const usage = await this.redis.hgetall(key);

    return {
      inputTokens: parseInt(usage.input_tokens || "0"),
      outputTokens: parseInt(usage.output_tokens || "0"),
      totalTokens: parseInt(usage.input_tokens || "0") + parseInt(usage.output_tokens || "0"),
    };
  }

  // Memory storage quotas
  async checkMemoryQuota(companionId: string, userId: string): Promise<boolean> {
    const stats = await db.execute(sql`
      SELECT 
        COUNT(*) as memory_count,
        SUM(pg_column_size(content) + pg_column_size(embedding)) as storage_bytes
      FROM memories
      WHERE companion_id = ${companionId} AND user_id = ${userId}
    `);

    const limits = await this.getCompanionLimits(companionId);
    
    return (
      stats.rows[0].memory_count < limits.maxMemoriesPerUser &&
      stats.rows[0].storage_bytes < limits.maxMemoryStorage * 1024 * 1024
    );
  }
}
```

## Monitoring and Analytics

### Companion Analytics

```typescript
// src/analytics/companionAnalytics.ts
export class CompanionAnalytics {
  async getCompanionMetrics(companionId: string, period = "7d") {
    const metrics = await db.execute(sql`
      WITH time_series AS (
        SELECT generate_series(
          NOW() - INTERVAL '${period}',
          NOW(),
          INTERVAL '1 hour'
        ) as hour
      ),
      hourly_stats AS (
        SELECT 
          date_trunc('hour', created_at) as hour,
          COUNT(*) as interactions,
          COUNT(DISTINCT user_id) as unique_users,
          AVG(importance) as avg_importance
        FROM memories
        WHERE 
          companion_id = ${companionId}
          AND created_at > NOW() - INTERVAL '${period}'
        GROUP BY date_trunc('hour', created_at)
      )
      SELECT 
        ts.hour,
        COALESCE(hs.interactions, 0) as interactions,
        COALESCE(hs.unique_users, 0) as unique_users,
        COALESCE(hs.avg_importance, 0) as avg_importance
      FROM time_series ts
      LEFT JOIN hourly_stats hs ON ts.hour = hs.hour
      ORDER BY ts.hour
    `);

    return metrics.rows;
  }

  async getUserEngagement(companionId: string) {
    const engagement = await db.execute(sql`
      SELECT 
        u.id as user_id,
        COUNT(m.id) as memory_count,
        MAX(m.created_at) as last_interaction,
        AVG(m.importance) as avg_importance,
        EXTRACT(EPOCH FROM (MAX(m.created_at) - MIN(m.created_at))) / 86400 as days_active
      FROM users u
      JOIN memories m ON u.id = m.user_id
      WHERE m.companion_id = ${companionId}
      GROUP BY u.id
      ORDER BY memory_count DESC
    `);

    return engagement.rows;
  }

  async getCompanionLeaderboard() {
    const leaderboard = await db.execute(sql`
      SELECT 
        c.id,
        c.name,
        COUNT(DISTINCT m.user_id) as total_users,
        COUNT(m.id) as total_memories,
        AVG(m.importance) as avg_importance,
        MAX(m.created_at) as last_activity
      FROM companions c
      LEFT JOIN memories m ON c.id = m.companion_id
      WHERE c.status = 'active'
      GROUP BY c.id, c.name
      ORDER BY total_users DESC, total_memories DESC
      LIMIT 20
    `);

    return leaderboard.rows;
  }
}
```

## Best Practices

1. **Implement strict tenant isolation** at the database level
2. **Use companion-specific encryption keys** for sensitive data
3. **Monitor companion health** and automatically pause unhealthy ones
4. **Implement rate limiting** per companion and per user
5. **Track usage metrics** for billing and optimization
6. **Version companion configurations** for rollback capability
7. **Use Redis for session state** to enable horizontal scaling
8. **Implement companion-specific caching** strategies
9. **Regular audit logs** for compliance and debugging
10. **Automated cleanup** of inactive companions and expired sessions

Always design with multi-tenancy, security, and scalability as core requirements for production companion services.
