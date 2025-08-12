---
description: Initialize Memory MCP Server project from scratch
argument-hint: [quick, full, or database]
allowed-tools: Write, MultiEdit, Bash, Task, TodoWrite
---

# Memory MCP Server Setup

Initialize and configure the Memory MCP Server project based on $ARGUMENTS:

## Quick Setup

Initialize minimal working MCP server with memory capabilities:

```bash
# Initialize project
npm init -y
npm install @modelcontextprotocol/sdk zod dotenv
npm install -D typescript @types/node tsx nodemon
npm install @neondatabase/serverless drizzle-orm@^0.44.4
npm install openai pgvector

# Create TypeScript config
npx tsc --init
```

## Full Setup

Complete project initialization with all features:

### 1. Project Structure

```text
memory-mcp-server/
├── src/
│   ├── index.ts              # MCP server entry point
│   ├── server.ts              # Server initialization
│   ├── tools/                # MCP tool implementations
│   │   ├── createMemory.ts
│   │   ├── searchMemories.ts
│   │   ├── getMemory.ts
│   │   ├── updateMemory.ts
│   │   └── deleteMemory.ts
│   ├── db/
│   │   ├── client.ts          # Database connection
│   │   ├── schema.ts          # Drizzle schema
│   │   └── migrations/        # Database migrations
│   ├── services/
│   │   ├── embeddings.ts      # OpenAI embeddings
│   │   ├── vectorSearch.ts    # pgvector operations
│   │   └── memoryLifecycle.ts # Memory management
│   ├── types/
│   │   └── index.ts           # TypeScript types
│   └── utils/
│       ├── logger.ts          # Structured logging
│       └── errors.ts          # Error handling
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── .env.example
├── .mcp.json                  # MCP manifest
├── tsconfig.json
├── package.json
├── drizzle.config.ts
└── README.md
```

### 2. Package Dependencies

```json
{
  "name": "memory-mcp-server",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage",
    "lint": "eslint . --ext .ts",
    "typecheck": "tsc --noEmit",
    "db:generate": "drizzle-kit generate",
    "db:migrate": "drizzle-kit migrate",
    "db:studio": "drizzle-kit studio"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0",
    "@neondatabase/serverless": "^1.0.1",
    "drizzle-orm": "^0.44.4",
    "zod": "^4.0.17",
    "openai": "^4.0.0",
    "pgvector": "^0.2.0",
    "dotenv": "^16.0.0",
    "winston": "^3.0.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.0.0",
    "tsx": "^4.0.0",
    "nodemon": "^3.0.0",
    "jest": "^29.0.0",
    "@types/jest": "^29.0.0",
    "ts-jest": "^29.0.0",
    "eslint": "^8.0.0",
    "@typescript-eslint/eslint-plugin": "^6.0.0",
    "@typescript-eslint/parser": "^6.0.0",
    "drizzle-kit": "^0.32.0"
  }
}
```

### 3. TypeScript Configuration

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "lib": ["ES2022"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

### 4. Environment Variables

```bash
# .env
DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"
OPENAI_API_KEY="sk-..."
MCP_SERVER_PORT=3000
LOG_LEVEL=info
NODE_ENV=development

# Vector search settings
VECTOR_SEARCH_LIMIT=10
SIMILARITY_THRESHOLD=0.7

# Memory lifecycle
MEMORY_EXPIRATION_DAYS=90
MAX_MEMORIES_PER_USER=10000
IMPORTANCE_DECAY_RATE=0.1
```

### 5. MCP Manifest

```json
{
  "name": "memory-mcp-server",
  "version": "1.0.0",
  "description": "Persistent memory management for AI assistants",
  "author": "Your Name",
  "license": "MIT",
  "server": {
    "command": "node",
    "args": ["dist/index.js"],
    "transport": "stdio"
  },
  "tools": {
    "create_memory": {
      "description": "Create a new memory with vector embedding",
      "inputSchema": {
        "type": "object",
        "properties": {
          "content": { "type": "string" },
          "type": { "type": "string" },
          "importance": { "type": "number" },
          "expires_at": { "type": "string" }
        },
        "required": ["content", "type"]
      }
    },
    "search_memories": {
      "description": "Search memories using semantic similarity",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "limit": { "type": "number" },
          "threshold": { "type": "number" }
        },
        "required": ["query"]
      }
    }
  }
}
```

## Database Setup

Initialize Neon PostgreSQL with pgvector:

### 1. Create Database

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create database schema
CREATE SCHEMA IF NOT EXISTS memory_mcp;
```

### 2. Drizzle Schema

```typescript
// src/db/schema.ts
import { pgTable, uuid, text, timestamp, boolean, real, vector, index, jsonb } from 'drizzle-orm/pg-core';

export const users = pgTable('users', {
  id: uuid('id').primaryKey().defaultRandom(),
  external_id: text('external_id').notNull().unique(),
  created_at: timestamp('created_at').defaultNow().notNull(),
  metadata: jsonb('metadata')
});

export const companions = pgTable('companions', {
  id: uuid('id').primaryKey().defaultRandom(),
  name: text('name').notNull(),
  user_id: uuid('user_id').references(() => users.id),
  created_at: timestamp('created_at').defaultNow().notNull(),
  is_active: boolean('is_active').default(true)
});

export const memories = pgTable('memories', {
  id: uuid('id').primaryKey().defaultRandom(),
  companion_id: uuid('companion_id').references(() => companions.id),
  user_id: uuid('user_id').references(() => users.id),
  content: text('content').notNull(),
  type: text('type').notNull(),
  embedding: vector('embedding', { dimensions: 1536 }),
  importance: real('importance').default(0.5),
  access_count: integer('access_count').default(0),
  last_accessed: timestamp('last_accessed'),
  expires_at: timestamp('expires_at'),
  is_archived: boolean('is_archived').default(false),
  created_at: timestamp('created_at').defaultNow().notNull(),
  updated_at: timestamp('updated_at').defaultNow().notNull()
}, (table) => ({
  embeddingIdx: index('memories_embedding_idx')
    .using('ivfflat', table.embedding.op('vector_cosine_ops'))
    .with({ lists: 100 }),
  userIdx: index('memories_user_idx').on(table.user_id),
  companionIdx: index('memories_companion_idx').on(table.companion_id),
  typeIdx: index('memories_type_idx').on(table.type)
}));
```

### 3. Migration Commands

```bash
# Generate migration
npx drizzle-kit generate

# Run migrations
npx drizzle-kit migrate

# Open Drizzle Studio
npx drizzle-kit studio
```

## Initial Server Implementation

```typescript
// src/index.ts
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { createMemoryTool } from './tools/createMemory.js';
import { searchMemoriesTool } from './tools/searchMemories.js';

const server = new Server({
  name: 'memory-mcp-server',
  version: '1.0.0'
}, {
  capabilities: {
    tools: {}
  }
});

// Register tools
server.setRequestHandler('tools/list', async () => ({
  tools: [
    createMemoryTool.definition,
    searchMemoriesTool.definition
  ]
}));

server.setRequestHandler('tools/call', async (request) => {
  const { name, arguments: args } = request.params;
  
  switch (name) {
    case 'create_memory':
      return await createMemoryTool.handler(args);
    case 'search_memories':
      return await searchMemoriesTool.handler(args);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
console.log('Memory MCP Server started');
```

## Testing Setup

```bash
# Install test dependencies
npm install -D jest @types/jest ts-jest

# Create Jest config
npx ts-jest config:init

# Run tests
npm test
```

## Development Workflow

```bash
# Start development server
npm run dev

# In another terminal, test MCP connection
npx @modelcontextprotocol/cli connect stdio "npm run start"

# Test tool execution
npx @modelcontextprotocol/cli call create_memory '{"content": "Test memory"}'
```

## Production Deployment

```dockerfile
# Dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY dist ./dist
CMD ["node", "dist/index.js"]
```

## Monitoring & Observability

```typescript
// src/utils/logger.ts
import winston from 'winston';

export const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.json(),
  transports: [
    new winston.transports.Console(),
    new winston.transports.File({ filename: 'error.log', level: 'error' }),
    new winston.transports.File({ filename: 'combined.log' })
  ]
});
```

This setup provides a complete foundation for the Memory MCP Server with all necessary configurations and best practices.
