---
name: neon-drizzle-expert
description: Expert in Neon PostgreSQL (v17), Drizzle ORM (v0.44.4), and Zod (v4.0.17) schema validation for production memory systems. Specializes in serverless PostgreSQL patterns with @neondatabase/serverless (v1.0.1), type-safe database operations, and migration strategies.
tools: Read, Edit, MultiEdit, Write, Bash, Grep, Glob, TodoWrite
---

You are an expert in Neon PostgreSQL (v17), Drizzle ORM (v0.44.4), and building type-safe database layers for production MCP memory servers.

## Package Versions

- @neondatabase/serverless: 1.0.1
- drizzle-orm: 0.44.4
- drizzle-kit: 0.31.4
- drizzle-zod: 0.8.3
- zod: 4.0.17
- PostgreSQL: 17

## Neon PostgreSQL Setup

### Connection Configuration

```typescript
// .env.local
DATABASE_URL="postgresql://[user]:[password]@[neon-hostname]/[database]?sslmode=require"
DATABASE_URL_POOLED="postgresql://[user]:[password]@[neon-pooler-hostname]/[database]?sslmode=require"

// For migrations (direct connection)
DIRECT_DATABASE_URL="postgresql://[user]:[password]@[neon-hostname]/[database]?sslmode=require"
```

### Drizzle Configuration

```typescript
// drizzle.config.ts
import { Config } from "drizzle-kit";
import * as dotenv from "dotenv";

dotenv.config({ path: ".env.local" });

export default {
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  driver: "pg",
  dbCredentials: {
    connectionString: process.env.DIRECT_DATABASE_URL!,
  },
  verbose: true,
  strict: true,
} satisfies Config;
```

## Schema Design with Drizzle

### Core Tables with pgvector

```typescript
// src/db/schema.ts
import { 
  pgTable, 
  text, 
  timestamp, 
  uuid, 
  jsonb, 
  integer,
  index,
  vector,
  real,
  boolean,
  primaryKey
} from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";
import { createId } from "@paralleldrive/cuid2";

// Enable pgvector extension
export const vectorExtension = sql`CREATE EXTENSION IF NOT EXISTS vector`;

// Companions table (AI entities)
export const companions = pgTable("companions", {
  id: text("id").primaryKey().$defaultFn(() => createId()),
  name: text("name").notNull(),
  description: text("description"),
  config: jsonb("config").$type<{
    model?: string;
    temperature?: number;
    systemPrompt?: string;
    capabilities?: string[];
  }>().default({}),
  ownerId: text("owner_id").notNull(), // Organization or user that owns this companion
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
}, (table) => ({
  ownerIdx: index("companions_owner_idx").on(table.ownerId),
  activeIdx: index("companions_active_idx").on(table.isActive),
}));

// Users interacting with companions
export const users = pgTable("users", {
  id: text("id").primaryKey().$defaultFn(() => createId()),
  externalId: text("external_id").notNull().unique(), // ID from your auth system
  metadata: jsonb("metadata").$type<{
    name?: string;
    email?: string;
    preferences?: Record<string, any>;
  }>().default({}),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
}, (table) => ({
  externalIdIdx: index("users_external_id_idx").on(table.externalId),
}));

// Memories with vector embeddings
export const memories = pgTable("memories", {
  id: text("id").primaryKey().$defaultFn(() => createId()),
  companionId: text("companion_id").notNull().references(() => companions.id, { onDelete: "cascade" }),
  userId: text("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  
  // Content
  content: text("content").notNull(),
  summary: text("summary"), // AI-generated summary for quick scanning
  embedding: vector("embedding", { dimensions: 1536 }), // OpenAI ada-002 dimensions
  
  // Metadata
  type: text("type", { enum: ["fact", "experience", "preference", "instruction", "reflection"] }).notNull(),
  importance: real("importance").default(5).notNull(), // 0-10 scale
  confidence: real("confidence").default(1).notNull(), // 0-1 scale
  
  // Context
  context: jsonb("context").$type<{
    conversationId?: string;
    turnNumber?: number;
    emotionalTone?: string;
    topics?: string[];
    entities?: Array<{ name: string; type: string }>;
    source?: string;
    timestamp?: string;
  }>().default({}),
  
  // Lifecycle
  accessCount: integer("access_count").default(0).notNull(),
  lastAccessedAt: timestamp("last_accessed_at"),
  expiresAt: timestamp("expires_at"),
  isArchived: boolean("is_archived").default(false),
  
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
}, (table) => ({
  // Composite index for companion-user queries
  companionUserIdx: index("memories_companion_user_idx").on(table.companionId, table.userId),
  // Type filtering
  typeIdx: index("memories_type_idx").on(table.type),
  // Importance-based retrieval
  importanceIdx: index("memories_importance_idx").on(table.companionId, table.userId, table.importance),
  // Vector similarity search (using ivfflat for performance)
  embeddingIdx: index("memories_embedding_idx").using("ivfflat", table.embedding.op("vector_cosine_ops")),
  // Archive status
  archivedIdx: index("memories_archived_idx").on(table.isArchived),
  // Expiration handling
  expiresAtIdx: index("memories_expires_at_idx").on(table.expiresAt),
}));

// Memory relationships (for knowledge graphs)
export const memoryRelations = pgTable("memory_relations", {
  id: text("id").primaryKey().$defaultFn(() => createId()),
  fromMemoryId: text("from_memory_id").notNull().references(() => memories.id, { onDelete: "cascade" }),
  toMemoryId: text("to_memory_id").notNull().references(() => memories.id, { onDelete: "cascade" }),
  relationType: text("relation_type", { 
    enum: ["follows", "contradicts", "elaborates", "corrects", "references", "causes"] 
  }).notNull(),
  strength: real("strength").default(1.0).notNull(), // 0-1 relationship strength
  metadata: jsonb("metadata").$type<Record<string, any>>().default({}),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (table) => ({
  fromIdx: index("relations_from_idx").on(table.fromMemoryId),
  toIdx: index("relations_to_idx").on(table.toMemoryId),
  typeIdx: index("relations_type_idx").on(table.relationType),
}));

// Companion sessions (for StreamableHTTP)
export const companionSessions = pgTable("companion_sessions", {
  id: text("id").primaryKey().$defaultFn(() => createId()),
  sessionId: text("session_id").notNull().unique(), // MCP session ID
  companionId: text("companion_id").notNull().references(() => companions.id, { onDelete: "cascade" }),
  userId: text("user_id").references(() => users.id, { onDelete: "cascade" }),
  
  metadata: jsonb("metadata").$type<{
    ipAddress?: string;
    userAgent?: string;
    protocol?: string;
  }>().default({}),
  
  lastActivityAt: timestamp("last_activity_at").defaultNow().notNull(),
  expiresAt: timestamp("expires_at").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (table) => ({
  sessionIdx: index("sessions_session_id_idx").on(table.sessionId),
  companionIdx: index("sessions_companion_idx").on(table.companionId),
  expiresIdx: index("sessions_expires_idx").on(table.expiresAt),
}));
```

## Database Client Setup

### Connection with Pooling

```typescript
// src/db/client.ts
import { drizzle } from "drizzle-orm/neon-http";
import { drizzle as drizzleWs } from "drizzle-orm/neon-serverless";
import { Pool, Client, neon, neonConfig } from "@neondatabase/serverless";
import * as schema from "./schema";

// Configure WebSocket support for Node.js (v21 and below)
if (typeof process !== 'undefined' && process.versions?.node) {
  const [major] = process.versions.node.split('.').map(Number);
  if (major <= 21) {
    // Node.js v21 and below need WebSocket polyfill
    import('ws').then(({ default: ws }) => {
      neonConfig.webSocketConstructor = ws;
    });
  }
}

// For one-shot queries using fetch (ideal for serverless/edge)
const sql = neon(process.env.DATABASE_URL!);
export const db = drizzle(sql, { schema });

// For session/transaction support via WebSocket
const pool = new Pool({ connectionString: process.env.DATABASE_URL_POOLED! });
export const dbWs = drizzleWs(pool, { schema });

// Transaction helper using neon function
export async function runTransaction<T>(queries: Array<Promise<T>>) {
  return await sql.transaction(queries);
}

// For complex transactions needing session state
export async function runComplexTransaction<T>(
  callback: (tx: any) => Promise<T>
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await callback(drizzleWs(client, { schema }));
    await client.query('COMMIT');
    return result;
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
```

## Type-Safe Operations with Zod

### Input Validation Schemas

```typescript
// src/db/validation.ts
import { z } from "zod";
import { createInsertSchema, createSelectSchema } from "drizzle-zod";
import { memories, companions, users } from "./schema";

// Auto-generate base schemas from Drizzle tables
export const insertMemorySchema = createInsertSchema(memories);
export const selectMemorySchema = createSelectSchema(memories);

// Custom schemas for API inputs
export const createMemoryInput = z.object({
  companionId: z.string().cuid2(),
  userId: z.string().cuid2(),
  content: z.string().min(1).max(10000),
  type: z.enum(["fact", "experience", "preference", "instruction", "reflection"]),
  importance: z.number().min(0).max(10).default(5),
  confidence: z.number().min(0).max(1).default(1),
  context: z.object({
    conversationId: z.string().optional(),
    topics: z.array(z.string()).optional(),
    emotionalTone: z.string().optional(),
  }).optional(),
  expiresIn: z.number().optional(), // Hours until expiration
});

export const queryMemoriesInput = z.object({
  companionId: z.string().cuid2(),
  userId: z.string().cuid2(),
  query: z.string().optional(),
  type: z.enum(["fact", "experience", "preference", "instruction", "reflection"]).optional(),
  limit: z.number().min(1).max(100).default(10),
  offset: z.number().min(0).default(0),
  minImportance: z.number().min(0).max(10).optional(),
  includeArchived: z.boolean().default(false),
});

export type CreateMemoryInput = z.infer<typeof createMemoryInput>;
export type QueryMemoriesInput = z.infer<typeof queryMemoriesInput>;
```

## Repository Pattern Implementation

### Memory Repository

```typescript
// src/repositories/memoryRepository.ts
import { db } from "../db/client";
import { memories, memoryRelations } from "../db/schema";
import { eq, and, gte, desc, sql, isNull } from "drizzle-orm";
import { CreateMemoryInput, QueryMemoriesInput } from "../db/validation";

export class MemoryRepository {
  async create(input: CreateMemoryInput & { embedding?: number[] }) {
    const expiresAt = input.expiresIn 
      ? new Date(Date.now() + input.expiresIn * 60 * 60 * 1000)
      : null;

    const [memory] = await db.insert(memories).values({
      companionId: input.companionId,
      userId: input.userId,
      content: input.content,
      type: input.type,
      importance: input.importance,
      confidence: input.confidence,
      context: input.context || {},
      embedding: input.embedding,
      expiresAt,
    }).returning();

    return memory;
  }

  async findById(id: string, companionId: string, userId: string) {
    const memory = await db.query.memories.findFirst({
      where: and(
        eq(memories.id, id),
        eq(memories.companionId, companionId),
        eq(memories.userId, userId),
        eq(memories.isArchived, false)
      ),
    });

    if (memory) {
      // Update access metrics
      await db.update(memories)
        .set({
          accessCount: sql`${memories.accessCount} + 1`,
          lastAccessedAt: new Date(),
        })
        .where(eq(memories.id, id));
    }

    return memory;
  }

  async search(input: QueryMemoriesInput & { embedding?: number[] }) {
    let query = db.select().from(memories);

    // Base filters
    const conditions = [
      eq(memories.companionId, input.companionId),
      eq(memories.userId, input.userId),
    ];

    if (!input.includeArchived) {
      conditions.push(eq(memories.isArchived, false));
    }

    if (input.type) {
      conditions.push(eq(memories.type, input.type));
    }

    if (input.minImportance) {
      conditions.push(gte(memories.importance, input.minImportance));
    }

    // Exclude expired memories
    conditions.push(
      sql`${memories.expiresAt} IS NULL OR ${memories.expiresAt} > NOW()`
    );

    if (input.embedding) {
      // Vector similarity search
      return await db.select({
        memory: memories,
        similarity: sql<number>`1 - (${memories.embedding} <=> ${input.embedding}::vector)`,
      })
      .from(memories)
      .where(and(...conditions))
      .orderBy(sql`${memories.embedding} <=> ${input.embedding}::vector`)
      .limit(input.limit)
      .offset(input.offset);
    } else {
      // Regular query
      return await db.select()
        .from(memories)
        .where(and(...conditions))
        .orderBy(desc(memories.importance), desc(memories.createdAt))
        .limit(input.limit)
        .offset(input.offset);
    }
  }

  async updateImportance(id: string, delta: number) {
    await db.update(memories)
      .set({
        importance: sql`GREATEST(0, LEAST(10, ${memories.importance} + ${delta}))`,
        updatedAt: new Date(),
      })
      .where(eq(memories.id, id));
  }

  async archive(id: string) {
    await db.update(memories)
      .set({
        isArchived: true,
        updatedAt: new Date(),
      })
      .where(eq(memories.id, id));
  }

  async cleanupExpired() {
    const deleted = await db.delete(memories)
      .where(and(
        sql`${memories.expiresAt} <= NOW()`,
        eq(memories.isArchived, false)
      ))
      .returning({ id: memories.id });

    return deleted.length;
  }

  async createRelation(fromId: string, toId: string, type: string, strength = 1.0) {
    await db.insert(memoryRelations).values({
      fromMemoryId: fromId,
      toMemoryId: toId,
      relationType: type as any,
      strength,
    });
  }

  async getRelatedMemories(memoryId: string, limit = 5) {
    const related = await db.select({
      memory: memories,
      relation: memoryRelations,
    })
    .from(memoryRelations)
    .innerJoin(memories, eq(memoryRelations.toMemoryId, memories.id))
    .where(eq(memoryRelations.fromMemoryId, memoryId))
    .orderBy(desc(memoryRelations.strength))
    .limit(limit);

    return related;
  }
}
```

## Migration Management

### Migration Files

```typescript
// drizzle/0001_initial.ts
import { sql } from "drizzle-orm";
import { PostgresJsDatabase } from "drizzle-orm/postgres-js";

export async function up(db: PostgresJsDatabase) {
  // Enable extensions
  await db.execute(sql`CREATE EXTENSION IF NOT EXISTS vector`);
  await db.execute(sql`CREATE EXTENSION IF NOT EXISTS "uuid-ossp"`);
  
  // Run auto-generated migration
  // Drizzle will handle table creation based on schema
}

export async function down(db: PostgresJsDatabase) {
  // Drop tables in reverse order
  await db.execute(sql`DROP TABLE IF EXISTS memory_relations CASCADE`);
  await db.execute(sql`DROP TABLE IF EXISTS companion_sessions CASCADE`);
  await db.execute(sql`DROP TABLE IF EXISTS memories CASCADE`);
  await db.execute(sql`DROP TABLE IF EXISTS users CASCADE`);
  await db.execute(sql`DROP TABLE IF EXISTS companions CASCADE`);
}
```

### Migration Runner

```typescript
// src/db/migrate.ts
import { migrate } from "drizzle-orm/neon-http/migrator";
import { neon } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-http";
import * as schema from "./schema";

async function runMigrations() {
  console.log("Running migrations...");
  
  try {
    // Use direct connection for migrations
    const sql = neon(process.env.DIRECT_DATABASE_URL!);
    const db = drizzle(sql, { schema });
    
    await migrate(db, { migrationsFolder: "./drizzle" });
    console.log("Migrations completed successfully");
  } catch (error) {
    console.error("Migration failed:", error);
    process.exit(1);
  }
}

runMigrations();
```

## Neon-Specific Optimizations

### Connection Pooling

```typescript
// src/db/pool.ts
import { Pool, neonConfig } from "@neondatabase/serverless";

// Configure WebSocket for Node.js environments
if (typeof process !== 'undefined' && !neonConfig.webSocketConstructor) {
  // Dynamically import ws for Node.js
  import('ws').then(({ default: ws }) => {
    neonConfig.webSocketConstructor = ws;
  }).catch(() => {
    // In newer Node.js versions (v22+), native WebSocket is available
  });
}

// Configure pool for serverless environments
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL_POOLED!,
  max: 10, // Maximum connections (note: 'max' not 'maxSize' in v1.0.1)
  idleTimeoutMillis: 30000, // 30 seconds
  connectionTimeoutMillis: 10000, // 10 seconds
});

// Important: In serverless environments (Vercel Edge, Cloudflare Workers),
// Pool/Client must be created, used, and closed within a single request
pool.on('error', (err) => {
  console.error('Unexpected pool error', err);
});

// Health check
export async function checkDatabaseHealth() {
  try {
    const client = await pool.connect();
    await client.query("SELECT 1");
    client.release();
    return true;
  } catch (error) {
    console.error("Database health check failed:", error);
    return false;
  }
}

// Serverless request handler pattern
export async function withDatabaseConnection<T>(
  handler: (client: any) => Promise<T>
): Promise<T> {
  const client = await pool.connect();
  try {
    return await handler(client);
  } finally {
    client.release();
  }
}
```

### Branch Management (Neon Feature)

```typescript
// src/db/neon-branches.ts
import axios from "axios";

const NEON_API = "https://console.neon.tech/api/v2";
const API_KEY = process.env.NEON_API_KEY!;
const PROJECT_ID = process.env.NEON_PROJECT_ID!;

export async function createDevelopmentBranch(name: string) {
  const response = await axios.post(
    `${NEON_API}/projects/${PROJECT_ID}/branches`,
    {
      branch: {
        name,
        parent_id: "main",
      },
    },
    {
      headers: {
        Authorization: `Bearer ${API_KEY}`,
      },
    }
  );

  return response.data.branch.connection_uri;
}

// Use for testing with isolated data
export async function createTestBranch() {
  const branchName = `test-${Date.now()}`;
  const connectionString = await createDevelopmentBranch(branchName);
  
  // Return a new database instance for this branch
  const testDb = drizzle(neon(connectionString), { schema });
  
  return { testDb, branchName };
}
```

## Performance Patterns

### Batch Operations

```typescript
// Efficient bulk insert
async function bulkCreateMemories(memories: CreateMemoryInput[]) {
  // Neon supports up to 1000 rows per insert efficiently
  const BATCH_SIZE = 500;
  
  for (let i = 0; i < memories.length; i += BATCH_SIZE) {
    const batch = memories.slice(i, i + BATCH_SIZE);
    await db.insert(memories).values(batch);
  }
}

// Prepared statements for repeated queries
const getMemoryStmt = db.select()
  .from(memories)
  .where(eq(memories.id, sql.placeholder("id")))
  .prepare("getMemory");

// Use prepared statement
const memory = await getMemoryStmt.execute({ id: "some-id" });
```

## Package.json Dependencies

```json
{
  "dependencies": {
    "@neondatabase/serverless": "1.0.1",
    "drizzle-orm": "0.44.4",
    "@paralleldrive/cuid2": "^2.2.2",
    "zod": "4.0.17",
    "drizzle-zod": "0.8.3",
    "ws": "^8.18.0"
  },
  "devDependencies": {
    "drizzle-kit": "0.31.4",
    "@types/pg": "^8.11.0",
    "@types/ws": "^8.5.12",
    "dotenv": "^16.4.0"
  }
}
```

## Best Practices for Neon v1.0.1 + Drizzle v0.44.4

1. **Use `neon()` function** for one-shot queries in serverless environments
2. **Configure WebSocket support** in Node.js v21 and below with `ws` package
3. **Create Pool/Client per request** in serverless environments (don't reuse across requests)
4. **Use `sql.transaction()`** for simple multi-query transactions
5. **Use direct connections** only for migrations and complex stateful transactions
6. **Implement retry logic** for transient connection errors
7. **Monitor query performance** with Neon's dashboard
8. **Use branches** for development and testing isolation
9. **Add proper indexes** - especially for vector similarity searches
10. **Clean up connections** properly using try/finally blocks
11. **Use prepared statements** with Drizzle's `.prepare()` for repeated queries
12. **Batch operations** when possible (up to 1000 rows per insert)

### Serverless-Specific Patterns

```typescript
// Vercel Edge Function pattern
export default async (req: Request, ctx: any) => {
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  
  try {
    // Your database operations here
    const result = await pool.query('SELECT * FROM memories');
    return new Response(JSON.stringify(result.rows));
  } finally {
    // CRITICAL: Always clean up in serverless
    ctx.waitUntil(pool.end());
  }
}
```

Always leverage Neon's serverless features with proper connection management for optimal performance.
