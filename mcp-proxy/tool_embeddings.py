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

import hashlib
import os
import asyncpg
from typing import Dict, List, Any, Optional

# Embedding model config
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM = 384

# How many texts the model is handed at once. onnxruntime keeps the memory a
# batch needed, so the batch size sets what this process holds for the rest of
# its life. Measured 2026-11-10 with the server's versions on the 336 real tool
# texts: 617 MB at fastembed's default of 256, 243 MB at 32, 207 MB at 8.
EMBED_BATCH = max(1, int(os.getenv("EMBED_BATCH", "32")))

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
    """Generate embedding vectors for multiple texts, EMBED_BATCH at a time."""
    model = get_embedding_model()
    if not model:
        return []

    return [emb.tolist() for emb in model.embed(texts, batch_size=EMBED_BATCH)]


def tool_text(tool_name: str, tool_info: Dict[str, Any]) -> str:
    """What one tool is embedded as.

    Format: "create_task - Create a new task in the workspace (server: ClickUp)".
    Unchanged from before, so the vectors already stored still match it.
    """
    original_name = tool_info.get("original_name", tool_name)
    description = tool_info.get("description", "")
    server_name = tool_info.get("tenant_name", tool_info.get("tenant_id", ""))
    return f"{original_name} - {description} (server: {server_name})"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def needing_embedding(texts: Dict[str, str],
                      stored: Dict[str, Optional[str]]) -> List[str]:
    """The tools whose vector is missing, or was made from other text.

    Every start used to embed all of them (2026-11-10: 336 tools, every start,
    while the table already held a vector for each). A row written before the
    hash existed has none, so it is embedded once more and then remembered.
    """
    return sorted(name for name, text in texts.items()
                  if stored.get(name) != text_hash(text))


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
        # Which text each vector was made from, so a start can tell what
        # changed instead of embedding everything again (2026-11-10).
        await conn.execute("""
            ALTER TABLE mcp_proxy.tool_embeddings
            ADD COLUMN IF NOT EXISTS text_hash TEXT
        """)


async def store_tool_embeddings(
    pool: asyncpg.Pool,
    tools_cache: Dict[str, Dict[str, Any]]
) -> int:
    """Generate and store embeddings for all cached tools."""
    if not tools_cache:
        log("No tools to embed")
        return 0

    await ensure_embeddings_table(pool)

    texts: Dict[str, str] = {}
    entries: Dict[str, Dict[str, Any]] = {}
    for tool_name, tool_info in tools_cache.items():
        texts[tool_name] = tool_text(tool_name, tool_info)
        entries[tool_name] = {
            "server_id": tool_info.get("tenant_id", ""),
            "display_name": tool_info.get("original_name", tool_name),
            "description": tool_info.get("description", ""),
        }

    # What the table already holds a vector for, and for which text.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tool_name, text_hash FROM mcp_proxy.tool_embeddings "
            "WHERE embedding IS NOT NULL")
    stored_hashes = {r["tool_name"]: r["text_hash"] for r in rows}
    todo = needing_embedding(texts, stored_hashes)
    log(f"Embedding {len(todo)} of {len(texts)} tools (the rest are unchanged)")

    vectors: Dict[str, List[float]] = {}
    if todo:
        embeddings = generate_embeddings_batch([texts[n] for n in todo])
        if not embeddings:
            # Metadata is still written below, so keyword search keeps working,
            # and the old hash stays, so the next start tries again.
            log("Failed to generate embeddings (fastembed not available?)")
        elif len(embeddings) != len(todo):
            log(f"Embedding count mismatch: {len(embeddings)} vs {len(todo)} tools")
        else:
            vectors = dict(zip(todo, embeddings))

    stored = 0
    async with pool.acquire() as conn:
        for tool_name, entry in entries.items():
            try:
                if tool_name in vectors:
                    vec_str = "[" + ",".join(str(x) for x in vectors[tool_name]) + "]"
                    await conn.execute("""
                        INSERT INTO mcp_proxy.tool_embeddings
                            (tool_name, server_id, display_name, description,
                             embedding, text_hash, updated_at)
                        VALUES ($1, $2, $3, $4, $5::vector, $6, NOW())
                        ON CONFLICT (tool_name) DO UPDATE SET
                            server_id = $2,
                            display_name = $3,
                            description = $4,
                            embedding = $5::vector,
                            text_hash = $6,
                            updated_at = NOW()
                    """,
                        tool_name, entry["server_id"], entry["display_name"],
                        entry["description"], vec_str, text_hash(texts[tool_name])
                    )
                else:
                    # Unchanged, or not embeddable this time: the vector and
                    # its hash are left exactly as they were.
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
                        tool_name, entry["server_id"], entry["display_name"],
                        entry["description"]
                    )
                stored += 1
            except Exception as e:
                log(f"Error storing {tool_name}: {e}")

    log(f"Stored {stored}/{len(entries)} tools, {len(vectors)} newly embedded")
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


def stale_tool_keys(indexed_rows, live_tools_by_server) -> set:
    """Indexed (server, tool) pairs whose server no longer lists that tool.

    unknown_server_ids answers "is this whole server gone". This answers
    the other half: a server that is still here but no longer has that
    tool.

    2026-11-06. The ClickUp catalogue was regenerated from ClickUp's own
    spec, so list_my_workspaces became get_authorized_teams.
    describe_tools correctly said "Tool not found" and call_tool correctly
    404'd, while search_tools went on OFFERING the old name, because the
    embeddings table is upserted and never cleaned and pruning only ever
    removed whole servers. my-clickup was still registered and enabled,
    so its renamed tools stayed searchable. Ralph's fresh chat picked the
    dead name five times and created nothing.

    The existing guard is kept, and it is the important half: a server
    that is up but momentarily failed to list its tools must keep every
    row, or one bad boot empties the index and nobody has any tools. So a
    server is pruned tool-by-tool ONLY when it actually listed tools this
    boot. A server absent from the listing is left to unknown_server_ids,
    because two rules answering one question is how this drifted.

    Pure, like unknown_server_ids, so the destructive decision is made
    and tested without a database.
    """
    live = live_tools_by_server if isinstance(live_tools_by_server, dict) else {}
    out = set()
    if not isinstance(indexed_rows, (list, tuple)):
        return out
    for row in indexed_rows:
        if not isinstance(row, dict):
            continue
        server = row.get("server_id")
        tool = row.get("tool_name")
        if not server or not tool:
            continue
        names = live.get(server)
        # Not listed this boot: say nothing about it.
        if not names:
            continue
        if tool not in names:
            out.add((server, tool))
    return out


async def prune_renamed_tools(pool: asyncpg.Pool, tools_cache) -> int:
    """Drop index rows for tools their own server no longer lists.

    The companion to prune_stale_tools, which only removes whole servers.
    A server that RENAMES a tool keeps the old row without this, and
    search goes on offering a name that describe_tools denies and
    call_tool 404s. See stale_tool_keys for what happened.
    """
    live: dict = {}
    for name, info in (tools_cache or {}).items():
        if not isinstance(info, dict):
            continue
        server = info.get("tenant_id")
        if server:
            live.setdefault(server, set()).add(name)
    if not live:
        return 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT server_id, tool_name FROM mcp_proxy.tool_embeddings")
            stale = stale_tool_keys(
                [{"server_id": r["server_id"], "tool_name": r["tool_name"]}
                 for r in rows], live)
            if not stale:
                return 0
            # One statement per server rather than a list of pairs:
            # asyncpg cannot send an anonymous composite, so
            # "(server_id, tool_name) = ANY($1::record[])" fails with
            # "input of anonymous composite types is not supported".
            # Measured on the box 2026-11-06, after the pure decision had
            # been tested and the SQL had not.
            by_server: dict = {}
            for server, tool in stale:
                by_server.setdefault(server, []).append(tool)
            deleted = []
            for server, names_to_go in by_server.items():
                deleted += await conn.fetch(
                    "DELETE FROM mcp_proxy.tool_embeddings "
                    "WHERE server_id = $1 AND tool_name = ANY($2::text[]) "
                    "RETURNING tool_name",
                    server, names_to_go)
        log(f"Pruned {len(deleted)} renamed or removed tools: "
            f"{sorted(t for _, t in stale)[:8]}")
        return len(deleted)
    except Exception as e:                                  # noqa: BLE001
        # Never fatal. An index with an extra row is worse than one that
        # could not be tidied, but neither is worth refusing to boot.
        log(f"Could not prune renamed tools: {e}")
        return 0


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
