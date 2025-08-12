---
description: Debug Memory MCP server connection and protocol issues
argument-hint: [connection issue, tool error, or specific debug scenario]
allowed-tools: Read, Grep, Bash, Edit, Task, TodoWrite
---

# Memory MCP Server Debugging

Debug the Memory MCP server implementation with focus on $ARGUMENTS:

## 1. Server Initialization & Configuration

- Verify MCP server startup and registration
- Check @modelcontextprotocol/sdk initialization
- Validate server manifest and capabilities
- Test stdio/HTTP transport configuration
- Verify database connection (Neon PostgreSQL)

## 2. MCP Protocol Compliance

- Validate JSON-RPC 2.0 message format
- Test request/response correlation (id matching)
- Verify error response format (code, message, data)
- Check notification handling (no id field)
- Validate batch request support

## 3. Memory Tool Registration

- Verify tool discovery and registration:
  - `create_memory` - Memory creation with embeddings
  - `search_memories` - Vector similarity search
  - `get_memory` - Direct retrieval
  - `update_memory` - Memory updates
  - `delete_memory` - Soft/hard deletion
  - `list_memories` - Pagination support
- Validate tool parameter schemas (Zod validation)
- Test tool permission boundaries

## 4. Database & Vector Operations

- Test pgvector extension functionality
- Verify embedding generation (OpenAI API)
- Debug vector similarity search queries
- Check index usage (IVFFlat/HNSW)
- Validate transaction handling

## 5. Session & Authentication

- Debug companion session management
- Verify user context isolation
- Test multi-tenancy boundaries
- Check session persistence
- Validate auth token handling

## 6. Error Handling & Recovery

- Test database connection failures
- Handle embedding API errors
- Verify graceful degradation
- Check error logging and telemetry
- Test retry mechanisms

## 7. Performance & Memory Leaks

- Monitor connection pooling
- Check for memory leaks in long sessions
- Verify streaming response handling
- Test concurrent request handling
- Profile vector search performance

## 8. Common Issues & Solutions

### Connection Refused

```bash
# Check if server is running
ps aux | grep "memory-mcp"
# Verify port binding
lsof -i :3000
# Test direct connection
npx @modelcontextprotocol/cli connect stdio "node ./dist/index.js"
```

### Tool Not Found

```bash
# List registered tools
npx @modelcontextprotocol/cli list-tools
# Verify tool manifest
cat .mcp.json
```

### Vector Search Failures

```sql
-- Check pgvector extension
SELECT * FROM pg_extension WHERE extname = 'vector';
-- Verify embeddings exist
SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL;
-- Test similarity query
SELECT id, content <=> '[...]'::vector AS distance 
FROM memories 
ORDER BY distance LIMIT 5;
```

## 9. Testing Checklist

- [ ] Server starts without errors
- [ ] Tools are discoverable via MCP protocol
- [ ] Memory CRUD operations work
- [ ] Vector search returns relevant results
- [ ] Session isolation is maintained
- [ ] Error responses follow MCP spec
- [ ] Performance meets requirements
- [ ] Logs provide debugging info
