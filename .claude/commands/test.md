---
description: Generate comprehensive tests for Memory MCP Server
argument-hint: [file, function, MCP tool, or test scenario]
allowed-tools: Read, Write, MultiEdit, Bash, Task, TodoWrite
---

# Memory MCP Server Test Generation

Generate comprehensive test cases for $ARGUMENTS with focus on MCP protocol compliance and memory operations:

## Unit Tests

### MCP Protocol Tests

```typescript
// Test MCP message handling
describe('MCP Protocol', () => {
  it('should handle JSON-RPC 2.0 requests', async () => {
    // Test request with id
    // Test notification without id
    // Test batch requests
  });
  
  it('should return proper error codes', async () => {
    // -32700: Parse error
    // -32600: Invalid request
    // -32601: Method not found
    // -32602: Invalid params
    // -32603: Internal error
  });
  
  it('should validate tool parameters with Zod', async () => {
    // Test required fields
    // Test type validation
    // Test nested schemas
  });
});
```

### Memory Operations Tests

```typescript
// Test memory CRUD operations
describe('Memory Operations', () => {
  it('should create memory with embeddings', async () => {
    // Test successful creation
    // Test OpenAI API failure handling
    // Test vector dimension validation
  });
  
  it('should perform vector similarity search', async () => {
    // Test similarity threshold
    // Test result limit
    // Test empty results
    // Test index usage
  });
  
  it('should handle memory lifecycle', async () => {
    // Test expiration
    // Test archival
    // Test soft delete
    // Test importance decay
  });
  
  it('should consolidate memories', async () => {
    // Test deduplication
    // Test summarization
    // Test relationship creation
  });
});
```

### Database Tests

```typescript
// Test database operations
describe('Database Operations', () => {
  it('should handle transactions', async () => {
    // Test commit on success
    // Test rollback on error
    // Test isolation levels
  });
  
  it('should use pgvector correctly', async () => {
    // Test vector operations
    // Test distance calculations
    // Test index scans
  });
  
  it('should maintain referential integrity', async () => {
    // Test foreign keys
    // Test cascade deletes
    // Test orphan prevention
  });
});
```

## Integration Tests

### MCP Server Integration

```typescript
// Test full MCP server flow
describe('MCP Server Integration', () => {
  let server: MCPServer;
  let client: MCPClient;
  
  beforeEach(async () => {
    server = await createMemoryMCPServer();
    client = await connectMCPClient(server);
  });
  
  it('should register tools on connection', async () => {
    const tools = await client.listTools();
    expect(tools).toContain('create_memory');
    expect(tools).toContain('search_memories');
  });
  
  it('should handle tool execution', async () => {
    const result = await client.executeTool('create_memory', {
      content: 'Test memory',
      type: 'fact'
    });
    expect(result.id).toBeDefined();
    expect(result.embedding).toHaveLength(1536);
  });
  
  it('should maintain session isolation', async () => {
    // Test multi-tenant boundaries
    // Test companion isolation
    // Test user context
  });
});
```

### Vector Search Integration

```typescript
// Test vector search functionality
describe('Vector Search Integration', () => {
  it('should find similar memories', async () => {
    // Create test memories
    // Generate embeddings
    // Test similarity search
    // Verify ranking
  });
  
  it('should use indexes efficiently', async () => {
    // Test IVFFlat performance
    // Test HNSW performance
    // Monitor query plans
  });
});
```

## Edge Cases & Error Conditions

```typescript
describe('Edge Cases', () => {
  it('should handle malformed requests', async () => {
    // Invalid JSON
    // Missing required fields
    // Wrong types
  });
  
  it('should handle resource limits', async () => {
    // Max memory count per user
    // Request size limits
    // Rate limiting
  });
  
  it('should handle concurrent operations', async () => {
    // Parallel memory creation
    // Concurrent searches
    // Session conflicts
  });
  
  it('should handle external service failures', async () => {
    // Database down
    // OpenAI API timeout
    // Network errors
  });
});
```

## Performance Tests

```typescript
describe('Performance', () => {
  it('should handle bulk operations', async () => {
    // Batch memory creation
    // Large result sets
    // Pagination
  });
  
  it('should meet latency requirements', async () => {
    // Vector search < 200ms
    // CRUD operations < 100ms
    // Tool registration < 50ms
  });
  
  it('should scale with data volume', async () => {
    // Test with 10K memories
    // Test with 100K memories
    // Test with 1M memories
  });
});
```

## Mock Strategies

```typescript
// Mocking external dependencies
const mocks = {
  // Mock OpenAI API
  openai: {
    embeddings: {
      create: jest.fn().mockResolvedValue({
        data: [{ embedding: new Array(1536).fill(0.1) }]
      })
    }
  },
  
  // Mock database
  db: {
    query: jest.fn(),
    transaction: jest.fn()
  },
  
  // Mock MCP client
  mcpClient: {
    request: jest.fn(),
    notify: jest.fn()
  }
};
```

## Test Data Fixtures

```typescript
// Reusable test data
export const fixtures = {
  memories: [
    {
      content: 'User prefers dark mode',
      type: 'preference',
      importance: 0.8
    },
    {
      content: 'Meeting scheduled for 3pm',
      type: 'event',
      expires_at: '2024-12-31'
    }
  ],
  
  embeddings: {
    sample: new Array(1536).fill(0.1),
    similar: new Array(1536).fill(0.09),
    different: new Array(1536).fill(0.5)
  },
  
  mcpRequests: {
    valid: {
      jsonrpc: '2.0',
      method: 'create_memory',
      params: { content: 'Test' },
      id: 1
    },
    invalid: {
      jsonrpc: '1.0', // Wrong version
      method: 'unknown_method'
    }
  }
};
```

## Test Coverage Requirements

- **Unit Tests**: 90% code coverage
- **Integration Tests**: All critical paths
- **E2E Tests**: Core user journeys
- **Performance Tests**: Load scenarios
- **Security Tests**: Auth and isolation

## Test Execution Commands

```bash
# Run all tests
npm test

# Run with coverage
npm run test:coverage

# Run specific test file
npm test -- memory.test.ts

# Run integration tests
npm run test:integration

# Run performance tests
npm run test:perf

# Watch mode for development
npm run test:watch
```
