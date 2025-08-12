---
description: Comprehensive code review for Memory MCP Server
argument-hint: [specific file, module, or leave empty for full review]
allowed-tools: Read, Grep, Glob, Task, TodoWrite
---

# Memory MCP Server Code Review

Perform a comprehensive review of $ARGUMENTS with focus on MCP protocol compliance and memory system integrity:

## Critical Security & Safety

- **Data Isolation**: Verify companion/user boundary enforcement
- **SQL Injection**: Check all database queries for parameterization
- **Embedding Leakage**: Ensure vector data doesn't cross tenant boundaries
- **Auth Tokens**: Validate secure storage and transmission
- **API Keys**: Check for hardcoded credentials (OpenAI, Neon)
- **Session Hijacking**: Review session management implementation

## MCP Protocol Compliance

- **JSON-RPC 2.0**: Validate message format compliance
- **Error Codes**: Use standard MCP error codes (-32700 to -32603)
- **Tool Registration**: Verify proper tool manifest structure
- **Parameter Validation**: Check Zod schemas match MCP expectations
- **Response Format**: Ensure consistent response structure
- **Streaming Support**: Validate partial result handling

## Memory System Integrity

- **Vector Dimensions**: Ensure consistent embedding dimensions (1536 for OpenAI)
- **Index Configuration**: Review IVFFlat/HNSW parameters
- **Memory Lifecycle**: Check expiration and archival logic
- **Consolidation Rules**: Validate memory merging algorithms
- **Importance Scoring**: Review decay and update mechanisms
- **Deduplication**: Check for duplicate memory prevention

## Performance Optimization

- **N+1 Queries**: Identify and fix database query patterns
- **Vector Search**: Optimize similarity thresholds and limits
- **Index Usage**: Verify proper index hints and scans
- **Connection Pooling**: Check pool size and timeout settings
- **Batch Operations**: Look for opportunities to batch DB operations
- **Caching Strategy**: Review memory and query result caching

## Database & Schema

- **Migration Safety**: Check for backward compatibility
- **Transaction Boundaries**: Verify ACID compliance
- **Deadlock Prevention**: Review lock ordering
- **Foreign Keys**: Ensure referential integrity
- **Soft Deletes**: Validate is_archived handling
- **Timestamps**: Check timezone handling

## Error Handling

- **Database Errors**: Graceful handling of connection failures
- **API Failures**: OpenAI API error recovery
- **Validation Errors**: User-friendly error messages
- **Timeout Handling**: Proper cleanup on timeouts
- **Retry Logic**: Exponential backoff implementation
- **Logging**: Structured logging with appropriate levels

## Code Quality

- **TypeScript Strict**: Enable strict mode compliance
- **Type Safety**: No `any` types without justification
- **Code Duplication**: Identify repeated patterns
- **Function Complexity**: Break down complex functions
- **Naming Conventions**: Consistent naming patterns
- **Documentation**: JSDoc for public APIs

## Testing Gaps

- **Unit Test Coverage**: Minimum 80% coverage
- **Integration Tests**: MCP protocol testing
- **Vector Search Tests**: Similarity threshold validation
- **Session Tests**: Multi-tenancy isolation
- **Error Path Tests**: Exception handling coverage
- **Performance Tests**: Load and stress testing

## Specific Checks for Memory MCP

```typescript
// Check for these patterns:
interface MemoryReviewChecks {
  // 1. Embedding generation should handle failures
  embeddings: {
    fallbackStrategy: boolean;
    retryLogic: boolean;
    costTracking: boolean;
  };
  
  // 2. Vector search should be bounded
  vectorSearch: {
    maxResults: number;
    minSimilarity: number;
    timeoutMs: number;
  };
  
  // 3. Memory operations should be atomic
  transactions: {
    useTransactions: boolean;
    rollbackOnError: boolean;
    isolationLevel: string;
  };
  
  // 4. Session management should be secure
  sessions: {
    tokenRotation: boolean;
    expirationHandling: boolean;
    revokeOnLogout: boolean;
  };
}
```

## Priority Issues Format

### 🔴 Critical (Security/Data Loss)

- Issue description
- File:line reference
- Suggested fix

### 🟡 Important (Performance/Reliability)

- Issue description
- File:line reference
- Suggested fix

### 🟢 Minor (Code Quality/Style)

- Issue description
- File:line reference
- Suggested fix

## Review Checklist

- [ ] No sensitive data in logs
- [ ] All DB queries parameterized
- [ ] MCP responses follow spec
- [ ] Vector operations are bounded
- [ ] Sessions properly isolated
- [ ] Errors handled gracefully
- [ ] Performance within targets
- [ ] Tests cover critical paths
