---
description: Monitor vector search performance and index efficiency for the memory MCP server
allowed-tools: Bash, Read, Grep
---

# Performance Monitoring Command

Monitor and analyze the performance of vector search operations, index efficiency, and memory lifecycle metrics.

## Usage

This command provides comprehensive performance monitoring for:

- Vector search query performance
- Index usage and efficiency
- Memory lifecycle statistics
- Database query patterns
- Resource utilization

## Available Monitoring Tasks

### 1. Vector Search Performance

```bash
# Check current pgvector index statistics
psql $DATABASE_URL -c "
  SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
  FROM pg_stat_user_indexes
  WHERE indexname LIKE '%vector%' OR indexname LIKE '%embedding%'
  ORDER BY idx_scan DESC;
"

# Analyze query performance for vector operations
psql $DATABASE_URL -c "
  SELECT 
    substring(query, 1, 50) as query_preview,
    calls,
    mean_exec_time as avg_ms,
    min_exec_time as min_ms,
    max_exec_time as max_ms,
    total_exec_time as total_ms,
    rows
  FROM pg_stat_statements
  WHERE query LIKE '%embedding%' OR query LIKE '%vector%'
  ORDER BY mean_exec_time DESC
  LIMIT 20;
"
```

### 2. Index Efficiency Analysis

```bash
# Check IVFFlat index clustering quality
psql $DATABASE_URL -c "
  SELECT 
    indexname,
    lists,
    pages,
    tuples,
    ROUND(tuples::numeric / NULLIF(lists, 0), 2) as avg_vectors_per_list,
    CASE 
      WHEN tuples::numeric / NULLIF(lists, 0) > 10000 THEN 'Rebalance recommended'
      WHEN tuples::numeric / NULLIF(lists, 0) < 100 THEN 'Over-partitioned'
      ELSE 'Optimal'
    END as status
  FROM (
    SELECT 
      'memories_embedding_ivfflat_idx'::regclass as indexname,
      (SELECT current_setting('ivfflat.lists')::int) as lists,
      relpages as pages,
      reltuples as tuples
    FROM pg_class 
    WHERE oid = 'memories_embedding_ivfflat_idx'::regclass
  ) index_stats;
"

# Check HNSW index parameters
psql $DATABASE_URL -c "
  SELECT 
    indexname,
    m,
    ef_construction,
    ef_search,
    CASE 
      WHEN ef_search < 100 THEN 'Low recall configuration'
      WHEN ef_search > 500 THEN 'High cost configuration'
      ELSE 'Balanced configuration'
    END as configuration_assessment
  FROM (
    SELECT 
      'memories_embedding_hnsw_idx' as indexname,
      current_setting('hnsw.m')::int as m,
      current_setting('hnsw.ef_construction')::int as ef_construction,
      current_setting('hnsw.ef_search')::int as ef_search
  ) hnsw_config;
"
```

### 3. Memory Lifecycle Metrics

```bash
# Memory distribution by status and type
psql $DATABASE_URL -c "
  SELECT 
    type,
    COUNT(*) FILTER (WHERE is_archived = false) as active,
    COUNT(*) FILTER (WHERE is_archived = true) as archived,
    AVG(importance) as avg_importance,
    AVG(access_count) as avg_accesses,
    AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400)::int as avg_age_days
  FROM memories
  GROUP BY type
  ORDER BY active DESC;
"

# Memory expiration analysis
psql $DATABASE_URL -c "
  SELECT 
    CASE 
      WHEN expires_at IS NULL THEN 'Never expires'
      WHEN expires_at < NOW() THEN 'Expired'
      WHEN expires_at < NOW() + INTERVAL '7 days' THEN 'Expiring soon'
      WHEN expires_at < NOW() + INTERVAL '30 days' THEN 'Expiring this month'
      ELSE 'Long-term'
    END as expiration_status,
    COUNT(*) as count,
    AVG(importance) as avg_importance
  FROM memories
  WHERE is_archived = false
  GROUP BY expiration_status
  ORDER BY count DESC;
"

# Consolidation statistics
psql $DATABASE_URL -c "
  SELECT 
    relation_type,
    COUNT(*) as relationship_count,
    COUNT(DISTINCT from_memory_id) as source_memories,
    COUNT(DISTINCT to_memory_id) as target_memories
  FROM memory_relations
  WHERE relation_type IN ('consolidated_into', 'summarized_in', 'elaborates', 'corrects')
  GROUP BY relation_type;
"
```

### 4. Query Pattern Analysis

```bash
# Analyze search patterns by limit size
psql $DATABASE_URL -c "
  WITH query_patterns AS (
    SELECT 
      CASE 
        WHEN query LIKE '%LIMIT 1%' THEN 'Single result'
        WHEN query LIKE '%LIMIT 5%' OR query LIKE '%LIMIT 10%' THEN 'Small batch'
        WHEN query LIKE '%LIMIT 50%' OR query LIKE '%LIMIT 100%' THEN 'Large batch'
        ELSE 'Variable'
      END as pattern,
      COUNT(*) as query_count,
      AVG(mean_exec_time) as avg_time_ms,
      SUM(calls) as total_calls
    FROM pg_stat_statements
    WHERE query LIKE '%ORDER BY % <=>%' -- Vector similarity queries
    GROUP BY pattern
  )
  SELECT * FROM query_patterns ORDER BY total_calls DESC;
"

# Identify slow queries
psql $DATABASE_URL -c "
  SELECT 
    substring(query, 1, 100) as query_preview,
    calls,
    mean_exec_time as avg_ms,
    max_exec_time as worst_ms,
    rows / NULLIF(calls, 0) as avg_rows_returned
  FROM pg_stat_statements
  WHERE 
    mean_exec_time > 100 -- Queries slower than 100ms
    AND (query LIKE '%memories%' OR query LIKE '%embedding%')
  ORDER BY mean_exec_time DESC
  LIMIT 10;
"
```

### 5. Storage and Resource Utilization

```bash
# Table and index sizes
psql $DATABASE_URL -c "
  SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) as index_size,
    n_live_tup as row_count,
    n_dead_tup as dead_rows,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) as dead_percent
  FROM pg_stat_user_tables
  WHERE tablename IN ('memories', 'memory_relations', 'companions', 'users', 'companion_sessions')
  ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Embedding storage analysis
psql $DATABASE_URL -c "
  SELECT 
    COUNT(*) as total_memories,
    COUNT(embedding) as memories_with_embeddings,
    pg_size_pretty(
      SUM(pg_column_size(embedding))
    ) as total_embedding_storage,
    pg_size_pretty(
      AVG(pg_column_size(embedding))::bigint
    ) as avg_embedding_size,
    COUNT(*) FILTER (WHERE embedding IS NULL) as missing_embeddings
  FROM memories;
"
```

### 6. Real-time Monitoring Dashboard

```bash
# Create a monitoring loop (run for 60 seconds)
echo "Starting real-time performance monitoring for 60 seconds..."
for i in {1..12}; do
  clear
  echo "=== Memory MCP Server Performance Monitor ==="
  echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
  echo ""
  
  # Active connections
  psql $DATABASE_URL -t -c "
    SELECT 'Active connections: ' || count(*) 
    FROM pg_stat_activity 
    WHERE state = 'active';
  "
  
  # Recent vector searches
  psql $DATABASE_URL -t -c "
    SELECT 'Vector searches (last min): ' || count(*)
    FROM pg_stat_statements
    WHERE query LIKE '%embedding%'
    AND last_call > NOW() - INTERVAL '1 minute';
  "
  
  # Memory operations
  psql $DATABASE_URL -t -c "
    SELECT 
      'Memories created (last hour): ' || 
      COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour')
    FROM memories;
  "
  
  # Cache hit ratio
  psql $DATABASE_URL -t -c "
    SELECT 'Cache hit ratio: ' || 
      ROUND(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) || '%'
    FROM pg_stat_database
    WHERE datname = current_database();
  "
  
  sleep 5
done
```

## Performance Tuning Recommendations

Based on monitoring results, consider these optimizations:

### For Slow Vector Searches

- Increase `ivfflat.probes` for better accuracy
- Enable iterative scans: `SET enable_iterative_index_scan = true`
- Consider switching from IVFFlat to HNSW for small result sets

### For Poor Index Performance

- Rebuild IVFFlat indexes if avg_vectors_per_list > 10000
- Increase HNSW `ef_search` for better recall
- Add more specific indexes for common query patterns

### For Memory Lifecycle Issues

- Adjust expiration policies based on usage patterns
- Implement more aggressive consolidation for old memories
- Archive memories with low importance scores

### For Storage Optimization

- Use halfvec type for less critical embeddings
- Implement memory pruning for users exceeding limits
- Compress archived memory content

## Integration with Application

To integrate monitoring into your application:

```typescript
// src/monitoring/performanceMonitor.ts
import { db } from "../db/client";
import { sql } from "drizzle-orm";

export class PerformanceMonitor {
  async getVectorSearchMetrics() {
    // Implementation based on queries above
  }
  
  async getIndexEfficiency() {
    // Implementation based on queries above
  }
  
  async getMemoryLifecycleStats() {
    // Implementation based on queries above
  }
}
```

## Automated Alerts

Set up alerts when:

- Average query time exceeds 200ms
- Index scan ratio drops below 90%
- Dead tuple percentage exceeds 20%
- Memory count approaches user limits
- Embedding generation fails repeatedly

## Export Metrics

Export monitoring data for analysis:

```bash
# Export to CSV
psql $DATABASE_URL -c "\COPY (
  SELECT * FROM pg_stat_user_indexes WHERE indexname LIKE '%vector%'
) TO '/tmp/index_stats.csv' WITH CSV HEADER;"

# Generate performance report
psql $DATABASE_URL -H -o performance_report.html -c "
  -- Your monitoring queries here
"
```

This command provides comprehensive monitoring capabilities for optimizing your memory MCP server's performance.
