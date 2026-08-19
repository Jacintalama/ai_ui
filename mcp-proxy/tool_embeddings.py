# mcp-proxy/tool_embeddings.py
"""
Tool Embeddings Module - Speakeasy Dynamic Toolsets

Provides semantic search over MCP tools using pgvector and fastembed.
Instead of exposing 200+ tools to the LLM, we expose 3 meta-tools:
  - search_tools: Find relevant tools by natural language query
  - describe_tools: Get full schema for specific tools
  - call_tool: Execute any tool by name

This reduces token usage by 96-99% while maintaining 100% tool access.

References:
  - Speakeasy paper: Dynamic Toolsets for LLM agents
  - pgvector: PostgreSQL vector similarity extension
  - fastembed: Lightweight Python embeddings (BAAI/bge-small-en-v1.5, 384-dim)
"""

import os
import asyncpg
from typing import Dict, List, Any, Optional

# Embedding model config
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM = 384

# Lazy-loaded embedding model
_embedding_model = None


def log(msg: str):
    """Debug logging."""
    print(f"[Embeddings] {msg}")


def get_embedding_model():
    """Lazy-load the fastembed model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from fastembed import TextEmbedding
            log(f"Loading model: {EMBEDDING_MODEL}...")
            _embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL)
            log(f"Model loaded: {EMBEDDING_MODEL}")
        except ImportError:
            log("fastembed not installed. Install with: pip install fastembed")
            return None
        except Exception as e:
            log(f"Error loading model: {e}")
            return None
    return _embedding_model


def generate_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding vector for a text string."""
    model = get_embedding_model()
    if not model:
        return None

    embeddings = list(model.embed([text]))
    if embeddings:
        return embeddings[0].tolist()
    return None


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embedding vectors for multiple texts."""
    model = get_embedding_model()
    if not model:
        return []

    return [emb.tolist() for emb in model.embed(texts)]


async def ensure_embeddings_table(pool: asyncpg.Pool):
    """Create the tool_embeddings table if it doesn't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_proxy.tool_embeddings (
                tool_name VARCHAR(512) PRIMARY KEY,
                server_id VARCHAR(255) NOT NULL,
                display_name VARCHAR(512),
                description TEXT,
                embedding vector(384),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Create index for vector similarity search (ivfflat for speed)
        # Note: ivfflat needs at least some rows to build. We use a low lists
        # count since we expect <1000 tools.
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tool_embeddings_vector
                ON mcp_proxy.tool_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 10)
            """)
        except Exception as e:
            # ivfflat index creation fails on empty tables, that's OK
            log(f"Index creation note: {e}")


async def store_tool_embeddings(
    pool: asyncpg.Pool,
    tools_cache: Dict[str, Dict[str, Any]]
) -> int:
    """Generate and store embeddings for all cached tools."""
    if not tools_cache:
        log("No tools to embed")
        return 0

    await ensure_embeddings_table(pool)

    # Build text representations for embedding
    tool_texts = []
    tool_entries = []

    for tool_name, tool_info in tools_cache.items():
        # Create a rich text representation combining name and description
        original_name = tool_info.get("original_name", tool_name)
        description = tool_info.get("description", "")
        server_name = tool_info.get("tenant_name", tool_info.get("tenant_id", ""))

        # Format: "create_task - Create a new task in the workspace (server: ClickUp)"
        text = f"{original_name} - {description} (server: {server_name})"

        tool_texts.append(text)
        tool_entries.append({
            "tool_name": tool_name,
            "server_id": tool_info.get("tenant_id", ""),
            "display_name": original_name,
            "description": description
        })

    # Generate embeddings in batch
    log(f"Generating embeddings for {len(tool_texts)} tools...")
    embeddings = generate_embeddings_batch(tool_texts)

    if not embeddings:
        log("Failed to generate embeddings (fastembed not available?)")
        # Still store tool metadata without embeddings for keyword fallback
        stored = 0
        async with pool.acquire() as conn:
            for entry in tool_entries:
                try:
                    await conn.execute("""
                        INSERT INTO mcp_proxy.tool_embeddings
                            (tool_name, server_id, display_name, description, updated_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        ON CONFLICT (tool_name) DO UPDATE SET
                            server_id = $2,
                            display_name = $3,
                            description = $4,
                            updated_at = NOW()
                    """,
                        entry["tool_name"],
                        entry["server_id"],
                        entry["display_name"],
                        entry["description"]
                    )
                    stored += 1
                except Exception as e:
                    log(f"Error storing metadata for {entry['tool_name']}: {e}")
        log(f"Stored {stored}/{len(tool_entries)} tool metadata (no embeddings)")
        return stored

    if len(embeddings) != len(tool_entries):
        log(f"Embedding count mismatch: {len(embeddings)} vs {len(tool_entries)} tools")
        return 0

    # Store in database
    stored = 0
    async with pool.acquire() as conn:
        for entry, embedding in zip(tool_entries, embeddings):
            try:
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
                await conn.execute("""
                    INSERT INTO mcp_proxy.tool_embeddings
                        (tool_name, server_id, display_name, description, embedding, updated_at)
                    VALUES ($1, $2, $3, $4, $5::vector, NOW())
                    ON CONFLICT (tool_name) DO UPDATE SET
                        server_id = $2,
                        display_name = $3,
                        description = $4,
                        embedding = $5::vector,
                        updated_at = NOW()
                """,
                    entry["tool_name"],
                    entry["server_id"],
                    entry["display_name"],
                    entry["description"],
                    vec_str
                )
                stored += 1
            except Exception as e:
                log(f"Error storing {entry['tool_name']}: {e}")

    log(f"Stored {stored}/{len(tool_entries)} tool embeddings")
    return stored


async def search_tools_by_query(
    pool: asyncpg.Pool,
    query: str,
    allowed_servers: Optional[List[str]] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Semantic search for tools matching a natural language query.

    Uses pgvector cosine similarity to find the most relevant tools.
    Optionally filtered by allowed server IDs (for access control).

    Returns list of dicts with: tool_name, server_id, display_name, description, relevance_score
    """
    # Generate query embedding
    query_embedding = generate_embedding(query)

    if query_embedding is None:
        # Fallback: keyword search
        log("No embedding model, using keyword fallback")
        return await _keyword_search(pool, query, allowed_servers, limit)

    vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    async with pool.acquire() as conn:
        # Set ivfflat probes high enough for accurate results
        await conn.execute("SET ivfflat.probes = 10")

        if allowed_servers:
            rows = await conn.fetch("""
                SELECT
                    tool_name,
                    server_id,
                    display_name,
                    description,
                    1 - (embedding <=> $1::vector) as similarity
                FROM mcp_proxy.tool_embeddings
                WHERE server_id = ANY($2)
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $3
            """, vec_str, allowed_servers, limit)
        else:
            rows = await conn.fetch("""
                SELECT
                    tool_name,
                    server_id,
                    display_name,
                    description,
                    1 - (embedding <=> $1::vector) as similarity
                FROM mcp_proxy.tool_embeddings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """, vec_str, limit)

    return [
        {
            "tool_name": row["tool_name"],
            "server_id": row["server_id"],
            "display_name": row["display_name"],
            "description": row["description"],
            "relevance_score": round(float(row["similarity"]), 4)
        }
        for row in rows
    ]


async def _keyword_search(
    pool: asyncpg.Pool,
    query: str,
    allowed_servers: Optional[List[str]] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Fallback keyword search when embeddings are unavailable."""
    # Split query into keywords for broader matching
    keywords = query.lower().split()
    # Build ILIKE conditions for each keyword
    search_pattern = f"%{query}%"

    async with pool.acquire() as conn:
        if allowed_servers:
            rows = await conn.fetch("""
                SELECT tool_name, server_id, display_name, description
                FROM mcp_proxy.tool_embeddings
                WHERE server_id = ANY($1)
                  AND (
                    tool_name ILIKE $2
                    OR description ILIKE $2
                    OR display_name ILIKE $2
                  )
                LIMIT $3
            """, allowed_servers, search_pattern, limit)
        else:
            rows = await conn.fetch("""
                SELECT tool_name, server_id, display_name, description
                FROM mcp_proxy.tool_embeddings
                WHERE tool_name ILIKE $1
                   OR description ILIKE $1
                   OR display_name ILIKE $1
                LIMIT $2
            """, search_pattern, limit)

    return [
        {
            "tool_name": row["tool_name"],
            "server_id": row["server_id"],
            "display_name": row["display_name"],
            "description": row["description"],
            "relevance_score": 0.5  # Fixed score for keyword matches
        }
        for row in rows
    ]


async def get_embeddings_stats(pool: asyncpg.Pool) -> Dict[str, Any]:
    """Get statistics about stored embeddings."""
    try:
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM mcp_proxy.tool_embeddings"
            )
            with_embeddings = await conn.fetchval(
                "SELECT COUNT(*) FROM mcp_proxy.tool_embeddings WHERE embedding IS NOT NULL"
            )
            servers = await conn.fetch(
                "SELECT server_id, COUNT(*) as count FROM mcp_proxy.tool_embeddings GROUP BY server_id ORDER BY count DESC"
            )
            return {
                "total_tools": total,
                "with_embeddings": with_embeddings,
                "without_embeddings": total - with_embeddings,
                "model": EMBEDDING_MODEL,
                "dimension": EMBEDDING_DIM,
                "by_server": {row["server_id"]: row["count"] for row in servers}
            }
    except Exception as e:
        return {"error": str(e)}


def unknown_server_ids(indexed_server_ids, live_server_ids) -> set:
    """Indexed server ids that no longer name a live server.

    Pure so the destructive decision can be tested without a database. An empty
    or missing `live_server_ids` prunes nothing: "the registry did not load" and
    "no server exists" have to stay distinct, or one bad boot empties the index.
    """
    live = set(live_server_ids or ())
    if not live:
        return set()
    return {sid for sid in (indexed_server_ids or ()) if sid not in live}


async def prune_stale_tools(pool: asyncpg.Pool, live_server_ids) -> int:
    """Drop index rows whose server is gone or disabled. Returns rows removed.

    store_tool_embeddings upserts and never deletes, so without this the index
    only grows. Production carried 48 tools that could be found and described
    and then could not be run.
    """
    live = set(live_server_ids or ())
    if not live:
        return 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT server_id FROM mcp_proxy.tool_embeddings")
            stale = unknown_server_ids(
                {r["server_id"] for r in rows}, live)
            if not stale:
                return 0
            deleted = await conn.fetch(
                "DELETE FROM mcp_proxy.tool_embeddings "
                "WHERE server_id = ANY($1::text[]) OR server_id IS NULL "
                "RETURNING tool_name",
                list(stale))
        log(f"Pruned {len(deleted)} tools from servers no longer live: "
            f"{sorted(stale)}")
        return len(deleted)
    except Exception as e:
        log(f"Prune skipped: {e}")
        return 0
