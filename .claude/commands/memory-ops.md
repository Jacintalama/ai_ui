---
description: Test and debug memory CRUD operations and vector search
argument-hint: [create, search, update, delete, lifecycle, or batch]
allowed-tools: Bash, Read, Write, Task, TodoWrite
---

# Memory Operations Testing

Test and debug memory operations for the Memory MCP Server focusing on $ARGUMENTS:

## Create Memory

Test memory creation with embedding generation:

```bash
# Create a simple memory
npx @modelcontextprotocol/cli call create_memory '{
  "content": "User prefers dark mode interfaces",
  "type": "preference",
  "importance": 0.8
}'

# Create memory with expiration
npx @modelcontextprotocol/cli call create_memory '{
  "content": "Meeting with team at 3pm tomorrow",
  "type": "event",
  "importance": 0.9,
  "expires_at": "2024-12-31T15:00:00Z"
}'

# Create memory with metadata
npx @modelcontextprotocol/cli call create_memory '{
  "content": "Project deadline is March 15",
  "type": "task",
  "importance": 1.0,
  "metadata": {
    "project": "Memory MCP Server",
    "priority": "high"
  }
}'

# Batch memory creation
for i in {1..10}; do
  npx @modelcontextprotocol/cli call create_memory "{
    \"content\": \"Test memory $i for performance testing\",
    \"type\": \"test\",
    \"importance\": 0.5
  }"
done
```

## Search Memories

Test vector similarity search:

```bash
# Basic semantic search
npx @modelcontextprotocol/cli call search_memories '{
  "query": "What are the user preferences?",
  "limit": 5
}'

# Search with similarity threshold
npx @modelcontextprotocol/cli call search_memories '{
  "query": "upcoming meetings and events",
  "limit": 10,
  "threshold": 0.7
}'

# Search by type
npx @modelcontextprotocol/cli call search_memories '{
  "query": "tasks and deadlines",
  "filter": {
    "type": "task"
  },
  "limit": 20
}'

# Search with date range
npx @modelcontextprotocol/cli call search_memories '{
  "query": "recent activities",
  "filter": {
    "created_after": "2024-01-01",
    "created_before": "2024-12-31"
  }
}'
```

## Update Memory

Test memory updates and importance adjustments:

```bash
# Update memory content
npx @modelcontextprotocol/cli call update_memory '{
  "id": "memory-uuid-here",
  "content": "Updated content with new information",
  "regenerate_embedding": true
}'

# Adjust importance
npx @modelcontextprotocol/cli call update_memory '{
  "id": "memory-uuid-here",
  "importance": 0.95
}'

# Extend expiration
npx @modelcontextprotocol/cli call update_memory '{
  "id": "memory-uuid-here",
  "expires_at": "2025-12-31T23:59:59Z"
}'

# Mark as accessed
npx @modelcontextprotocol/cli call update_memory '{
  "id": "memory-uuid-here",
  "increment_access_count": true
}'
```

## Delete Memory

Test soft and hard deletion:

```bash
# Soft delete (archive)
npx @modelcontextprotocol/cli call delete_memory '{
  "id": "memory-uuid-here",
  "soft_delete": true
}'

# Hard delete
npx @modelcontextprotocol/cli call delete_memory '{
  "id": "memory-uuid-here",
  "soft_delete": false
}'

# Bulk delete by filter
npx @modelcontextprotocol/cli call delete_memories '{
  "filter": {
    "type": "test",
    "created_before": "2024-01-01"
  }
}'
```

## Memory Lifecycle

Test expiration, archival, and consolidation:

```bash
# Process expired memories
npx @modelcontextprotocol/cli call process_expired_memories

# Archive old memories
npx @modelcontextprotocol/cli call archive_memories '{
  "older_than_days": 90,
  "importance_below": 0.3
}'

# Consolidate similar memories
npx @modelcontextprotocol/cli call consolidate_memories '{
  "similarity_threshold": 0.9,
  "max_group_size": 5
}'

# Apply importance decay
npx @modelcontextprotocol/cli call apply_importance_decay '{
  "decay_rate": 0.1,
  "days_inactive": 30
}'
```

## Batch Operations

Test bulk operations and performance:

```bash
# Bulk import memories
cat memories.json | npx @modelcontextprotocol/cli call bulk_import_memories

# Export memories
npx @modelcontextprotocol/cli call export_memories '{
  "format": "json",
  "include_embeddings": false
}' > backup.json

# Regenerate all embeddings
npx @modelcontextprotocol/cli call regenerate_embeddings '{
  "batch_size": 100,
  "model": "text-embedding-3-small"
}'
```

## Database Queries

Direct database operations for testing:

```sql
-- Check memory count
SELECT COUNT(*) as total,
       COUNT(CASE WHEN is_archived THEN 1 END) as archived,
       COUNT(CASE WHEN embedding IS NULL THEN 1 END) as no_embedding
FROM memories;

-- Find duplicate memories
SELECT content, COUNT(*) as count
FROM memories
WHERE is_archived = false
GROUP BY content
HAVING COUNT(*) > 1;

-- Analyze embedding distribution
SELECT 
  percentile_cont(0.5) WITHIN GROUP (ORDER BY importance) as median_importance,
  AVG(access_count) as avg_accesses,
  COUNT(DISTINCT user_id) as unique_users
FROM memories;

-- Test vector similarity manually
SELECT id, content,
       embedding <=> (SELECT embedding FROM memories WHERE id = 'reference-id') as distance
FROM memories
WHERE embedding IS NOT NULL
ORDER BY distance
LIMIT 10;
```

## Performance Testing

Load testing and benchmarking:

```bash
# Concurrent memory creation
for i in {1..100}; do
  (npx @modelcontextprotocol/cli call create_memory "{
    \"content\": \"Concurrent test $i\",
    \"type\": \"test\"
  }" &)
done
wait

# Measure search latency
time npx @modelcontextprotocol/cli call search_memories '{
  "query": "test query for performance measurement",
  "limit": 100
}'

# Stress test with large content
npx @modelcontextprotocol/cli call create_memory "{
  \"content\": \"$(cat large-document.txt)\",
  \"type\": \"document\"
}"
```

## Monitoring Commands

Real-time monitoring during operations:

```bash
# Watch memory creation rate
watch -n 1 'psql $DATABASE_URL -t -c "
  SELECT COUNT(*) || \" memories created in last minute\"
  FROM memories
  WHERE created_at > NOW() - INTERVAL \"1 minute\";
"'

# Monitor embedding generation
psql $DATABASE_URL -c "
  SELECT 
    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as with_embedding,
    COUNT(*) FILTER (WHERE embedding IS NULL) as without_embedding,
    pg_size_pretty(SUM(pg_column_size(embedding))) as total_size
  FROM memories;
"

# Check index usage
psql $DATABASE_URL -c "
  SELECT indexname, idx_scan, idx_tup_read, idx_tup_fetch
  FROM pg_stat_user_indexes
  WHERE tablename = 'memories'
  ORDER BY idx_scan DESC;
"
```

## Validation Scripts

Automated validation of memory operations:

```typescript
// validate-memory-ops.ts
import { MCPClient } from '@modelcontextprotocol/sdk';

async function validateMemoryOperations() {
  const client = new MCPClient();
  
  // Test 1: Create and retrieve
  const created = await client.call('create_memory', {
    content: 'Validation test memory',
    type: 'test'
  });
  
  const retrieved = await client.call('get_memory', {
    id: created.id
  });
  
  console.assert(created.id === retrieved.id, 'Memory retrieval failed');
  
  // Test 2: Search accuracy
  const searchResults = await client.call('search_memories', {
    query: 'Validation test memory',
    limit: 1
  });
  
  console.assert(searchResults[0].id === created.id, 'Search failed');
  
  // Test 3: Update verification
  await client.call('update_memory', {
    id: created.id,
    importance: 0.99
  });
  
  const updated = await client.call('get_memory', {
    id: created.id
  });
  
  console.assert(updated.importance === 0.99, 'Update failed');
  
  // Test 4: Cleanup
  await client.call('delete_memory', {
    id: created.id
  });
  
  console.log('✅ All memory operations validated');
}

validateMemoryOperations().catch(console.error);
```

## Common Issues & Solutions

### Embedding Generation Failures

```bash
# Check OpenAI API key
echo $OPENAI_API_KEY

# Test API directly
curl https://api.openai.com/v1/embeddings \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "text-embedding-3-small",
    "input": "Test"
  }'

# Retry failed embeddings
npx @modelcontextprotocol/cli call retry_failed_embeddings
```

### Vector Index Issues

```sql
-- Rebuild IVFFlat index
DROP INDEX IF EXISTS memories_embedding_idx;
CREATE INDEX memories_embedding_idx ON memories 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Switch to HNSW for better performance
CREATE INDEX memories_embedding_hnsw_idx ON memories 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### Memory Limit Exceeded

```bash
# Check user memory count
psql $DATABASE_URL -c "
  SELECT user_id, COUNT(*) as memory_count
  FROM memories
  WHERE is_archived = false
  GROUP BY user_id
  HAVING COUNT(*) > 9000
  ORDER BY memory_count DESC;
"

# Archive old memories for user
npx @modelcontextprotocol/cli call archive_user_memories '{
  "user_id": "user-uuid",
  "keep_recent": 5000
}'
```

This command provides comprehensive testing and debugging capabilities for all memory operations in the MCP server.

