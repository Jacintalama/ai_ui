import os
import hashlib
import logging
import asyncio
from typing import Optional
from datetime import datetime
from uuid import UUID
from contextlib import asynccontextmanager

import asyncpg
from fastembed import TextEmbedding
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("meeting-kb")
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ["DATABASE_URL"]
MEETING_KB_API_KEY = os.getenv("MEETING_KB_API_KEY", "")

db_pool: Optional[asyncpg.Pool] = None
embedder: Optional[TextEmbedding] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, embedder
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
    embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    # Seed API key from env if set
    if MEETING_KB_API_KEY:
        key_hash = hashlib.sha256(MEETING_KB_API_KEY.encode()).hexdigest()
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_proxy.meeting_api_keys (key_hash, description)
                   VALUES ($1, $2)
                   ON CONFLICT (key_hash) DO NOTHING""",
                key_hash, "Auto-seeded from MEETING_KB_API_KEY env var"
            )
    logger.info("Meeting KB started — embedding model loaded, DB pool ready")
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(
    title="Meeting Knowledge Base",
    description="Store and search meeting summaries. AI reads ONLY from this database.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class MeetingInput(BaseModel):
    title: str = Field(..., description="Meeting title")
    summary: str = Field(..., description="Full meeting summary or notes")
    meeting_date: datetime = Field(..., description="When the meeting occurred (ISO 8601)")
    participants: list[str] = Field(default_factory=list, description="List of attendees")
    tags: list[str] = Field(default_factory=list, description="Optional tags for categorization")
    source: str = Field(default="manual", description="Origin: n8n, manual, etc.")


class BulkMeetingInput(BaseModel):
    meetings: list[MeetingInput] = Field(..., max_length=50, description="List of meetings (max 50)")


class SearchInput(BaseModel):
    query: str = Field(..., description="Search query — will be matched semantically against meeting summaries")
    title_keyword: Optional[str] = Field(None, description="Optional keyword filter on title")
    date_from: Optional[datetime] = Field(None, description="Filter: meetings on or after this date")
    date_to: Optional[datetime] = Field(None, description="Filter: meetings on or before this date")
    participants: Optional[list[str]] = Field(None, description="Filter: meetings that include ALL of these participants")
    tags: Optional[list[str]] = Field(None, description="Filter: meetings that include ANY of these tags")
    limit: int = Field(default=10, ge=1, le=50, description="Max results")


class GetMeetingInput(BaseModel):
    meeting_id: str = Field(..., description="UUID of the meeting to retrieve")


class ListMeetingsInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=50, description="Number of meetings to return")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


# ---------------------------------------------------------------------------
# Auth & Embedding helpers
# ---------------------------------------------------------------------------

async def verify_api_key(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:]
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM mcp_proxy.meeting_api_keys WHERE key_hash = $1", key_hash
        )
    if not row:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def embed_text(text: str) -> list[float]:
    """Generate embedding for text (runs in thread to avoid blocking event loop)."""
    embeddings = await asyncio.to_thread(lambda: list(embedder.embed([text])))
    return embeddings[0].tolist()


# ---------------------------------------------------------------------------
# Upload API (for n8n — authenticated with API key)
# ---------------------------------------------------------------------------

@app.post("/api/meetings")
async def create_meeting(meeting: MeetingInput, authorization: str = Header(None)):
    await verify_api_key(authorization)
    embedding = await embed_text(f"{meeting.title} {meeting.summary}")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO mcp_proxy.meeting_summaries
               (title, summary, meeting_date, participants, tags, source, embedding)
               VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
               RETURNING id, title""",
            meeting.title, meeting.summary, meeting.meeting_date,
            meeting.participants, meeting.tags, meeting.source, str(embedding)
        )
    return {"id": str(row["id"]), "title": row["title"], "status": "created", "embedding_status": "generated"}


@app.post("/api/meetings/bulk")
async def create_meetings_bulk(bulk: BulkMeetingInput, authorization: str = Header(None)):
    await verify_api_key(authorization)
    results = []
    async with db_pool.acquire() as conn:
        for m in bulk.meetings:
            embedding = await embed_text(f"{m.title} {m.summary}")
            row = await conn.fetchrow(
                """INSERT INTO mcp_proxy.meeting_summaries
                   (title, summary, meeting_date, participants, tags, source, embedding)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
                   RETURNING id, title""",
                m.title, m.summary, m.meeting_date,
                m.participants, m.tags, m.source, str(embedding)
            )
            results.append({"id": str(row["id"]), "title": row["title"], "status": "created"})
    return {"count": len(results), "meetings": results}


@app.get("/api/meetings/{meeting_id}")
async def get_meeting_api(meeting_id: str, authorization: str = Header(None)):
    await verify_api_key(authorization)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, title, summary, meeting_date, participants, tags, source, created_at, updated_at
               FROM mcp_proxy.meeting_summaries WHERE id = $1""",
            UUID(meeting_id)
        )
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return dict(row)


@app.delete("/api/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, authorization: str = Header(None)):
    await verify_api_key(authorization)
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM mcp_proxy.meeting_summaries WHERE id = $1", UUID(meeting_id)
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": "deleted", "id": meeting_id}


# ---------------------------------------------------------------------------
# MCP Tools (exposed via MCP Proxy — no API key needed, trusted headers)
# ---------------------------------------------------------------------------

@app.post("/search_meetings", operation_id="search_meetings",
          summary="Search meeting summaries by topic, date, participants, or tags")
async def search_meetings(input: SearchInput, request: Request):
    """Semantic search across all meeting summaries. Use this to find meetings about specific topics,
    with specific people, or within a date range. Returns the most relevant meetings ranked by similarity."""

    query_embedding = await embed_text(input.query)

    conditions = []
    params = [str(query_embedding), input.limit]
    param_idx = 3

    if input.title_keyword:
        conditions.append(f"title ILIKE '%' || ${param_idx} || '%'")
        params.append(input.title_keyword)
        param_idx += 1

    if input.date_from:
        conditions.append(f"meeting_date >= ${param_idx}")
        params.append(input.date_from)
        param_idx += 1

    if input.date_to:
        conditions.append(f"meeting_date <= ${param_idx}")
        params.append(input.date_to)
        param_idx += 1

    if input.participants:
        conditions.append(f"participants @> ${param_idx}")
        params.append(input.participants)
        param_idx += 1

    if input.tags:
        conditions.append(f"tags && ${param_idx}")
        params.append(input.tags)
        param_idx += 1

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT id, title, summary, meeting_date, participants, tags, source,
               1 - (embedding <=> $1::vector) AS similarity
        FROM mcp_proxy.meeting_summaries
        {where_clause}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
    """

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "summary": r["summary"][:500] + ("..." if len(r["summary"]) > 500 else ""),
            "meeting_date": r["meeting_date"].isoformat(),
            "participants": r["participants"],
            "tags": r["tags"],
            "similarity": round(r["similarity"], 3),
        }
        for r in rows
    ]


@app.post("/get_meeting", operation_id="get_meeting",
          summary="Get full details of a specific meeting by its ID")
async def get_meeting_tool(input: GetMeetingInput, request: Request):
    """Retrieve the complete meeting summary including all participants, tags, and the full text.
    Use this after search_meetings to get the full details of a specific meeting."""

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, title, summary, meeting_date, participants, tags, source, created_at
               FROM mcp_proxy.meeting_summaries WHERE id = $1""",
            UUID(input.meeting_id)
        )
    if not row:
        return {"error": "Meeting not found", "meeting_id": input.meeting_id}
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "summary": row["summary"],
        "meeting_date": row["meeting_date"].isoformat(),
        "participants": row["participants"],
        "tags": row["tags"],
        "source": row["source"],
        "created_at": row["created_at"].isoformat(),
    }


@app.post("/list_meetings", operation_id="list_meetings",
          summary="List recent meeting summaries with pagination")
async def list_meetings(input: ListMeetingsInput, request: Request):
    """List the most recent meeting summaries, ordered by meeting date (newest first).
    Use this to see what meetings are available before searching for specific topics."""

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, meeting_date, participants, tags, source
               FROM mcp_proxy.meeting_summaries
               ORDER BY meeting_date DESC
               LIMIT $1 OFFSET $2""",
            input.limit, input.offset
        )
        count_row = await conn.fetchrow(
            "SELECT COUNT(*) as total FROM mcp_proxy.meeting_summaries"
        )

    return {
        "total": count_row["total"],
        "meetings": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "meeting_date": r["meeting_date"].isoformat(),
                "participants": r["participants"],
                "tags": r["tags"],
                "source": r["source"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Health & OpenAPI
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "meeting-kb"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200)
