# Meeting Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a meeting knowledge base MCP server that stores meeting summaries in PostgreSQL/pgvector, exposes them as AI tools, and accepts uploads from n8n via HTTP API.

**Architecture:** New `meeting-kb` FastAPI container (port 8200) with 3 MCP tools (search/get/list) + HTTP upload API. Uses fastembed for embeddings, HNSW index for vector search. API Gateway routes upload traffic directly to the container (bypassing MCP Proxy); tool calls route through MCP Proxy as normal.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, fastembed (ONNX Runtime), PostgreSQL/pgvector

**Spec:** `docs/superpowers/specs/2026-04-02-meeting-kb-design.md`

---

### Task 1: Database Schema — Migration & Init Scripts

**Files:**
- Create: `scripts/migrate-meeting-kb.sql`
- Modify: `scripts/init-db-hetzner.sql:259` (append after api_analytics section)

- [ ] **Step 1: Create migration script**

Create `scripts/migrate-meeting-kb.sql`:

```sql
-- Meeting Knowledge Base tables
-- Run this on existing deployments: psql -f scripts/migrate-meeting-kb.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- Updated_at trigger function (reusable)
CREATE OR REPLACE FUNCTION mcp_proxy.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TABLE IF NOT EXISTS mcp_proxy.meeting_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(512) NOT NULL,
    summary TEXT NOT NULL,
    meeting_date TIMESTAMPTZ NOT NULL,
    participants TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    source VARCHAR(128) DEFAULT 'manual',
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_date
    ON mcp_proxy.meeting_summaries (meeting_date DESC);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_participants
    ON mcp_proxy.meeting_summaries USING GIN (participants);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_tags
    ON mcp_proxy.meeting_summaries USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_embedding
    ON mcp_proxy.meeting_summaries USING hnsw (embedding vector_cosine_ops);

-- Updated_at trigger
DROP TRIGGER IF EXISTS update_meeting_summaries_updated_at ON mcp_proxy.meeting_summaries;
CREATE TRIGGER update_meeting_summaries_updated_at
    BEFORE UPDATE ON mcp_proxy.meeting_summaries
    FOR EACH ROW EXECUTE FUNCTION mcp_proxy.update_updated_at_column();

-- API keys for upload authentication
CREATE TABLE IF NOT EXISTS mcp_proxy.meeting_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    description VARCHAR(256) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

- [ ] **Step 2: Append same SQL to init-db-hetzner.sql**

Add the same SQL block to the end of `scripts/init-db-hetzner.sql` (after line 259), wrapped in a section header:

```sql
-- =============================================================================
-- MEETING KNOWLEDGE BASE
-- =============================================================================

-- (same SQL as migrate-meeting-kb.sql)
```

- [ ] **Step 3: Verify migration script syntax**

Run: `cat scripts/migrate-meeting-kb.sql | head -5`
Expected: The file exists and contains valid SQL.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate-meeting-kb.sql scripts/init-db-hetzner.sql
git commit -m "feat(meeting-kb): add database schema for meeting summaries"
```

---

### Task 2: MCP Server — Core Application

**Files:**
- Create: `mcp-servers/meeting-kb/main.py`
- Create: `mcp-servers/meeting-kb/requirements.txt`
- Create: `mcp-servers/meeting-kb/Dockerfile`

- [ ] **Step 1: Create requirements.txt**

Create `mcp-servers/meeting-kb/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
asyncpg==0.30.0
fastembed==0.4.1
pydantic==2.10.3
```

- [ ] **Step 2: Create Dockerfile**

Create `mcp-servers/meeting-kb/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps for fastembed/onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8200

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200"]
```

- [ ] **Step 3: Create main.py — imports and config**

Create `mcp-servers/meeting-kb/main.py` with the app setup, Pydantic models, and database pool:

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/meeting-kb/
git commit -m "feat(meeting-kb): add MCP server with tools and upload API"
```

---

### Task 3: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml:139` (add env var to mcp-proxy)
- Modify: `docker-compose.yml:179` (add depends_on to mcp-proxy)
- Modify: `docker-compose.yml:278` (add meeting-kb service after mcp-gmail)

- [ ] **Step 1: Add MCP_MEETING_KB_URL to mcp-proxy environment**

In `docker-compose.yml`, after line 139 (`MCP_GMAIL_URL=http://mcp-gmail:8000`), add:

```yaml
      - MCP_MEETING_KB_URL=http://meeting-kb:8200
```

- [ ] **Step 2: Add meeting-kb to mcp-proxy depends_on**

In `docker-compose.yml`, after line 179 (`mcp-gmail: condition: service_started`), add:

```yaml
      meeting-kb:
        condition: service_started
```

- [ ] **Step 3: Add meeting-kb service**

In `docker-compose.yml`, after line 278 (after the mcp-gmail service block, before the TIER 2 SSE section comment), add:

```yaml
  # ==========================================================================
  # MCP Meeting Knowledge Base - Search & Store Meeting Summaries
  # ==========================================================================
  meeting-kb:
    build: ./mcp-servers/meeting-kb
    container_name: meeting-kb
    ports:
      - "8200:8200"
    environment:
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      - MEETING_KB_API_KEY=${MEETING_KB_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(meeting-kb): add meeting-kb service to docker-compose"
```

---

### Task 4: MCP Proxy Registration

**Files:**
- Modify: `mcp-proxy/tenants.py:556` (add URL var after MCP_GMAIL_URL)
- Modify: `mcp-proxy/tenants.py:656` (add to LOCAL_SERVERS before closing brace)
- Modify: `mcp-proxy/config/mcp-servers.json:135` (add server entry before closing bracket)

- [ ] **Step 1: Add URL variable to tenants.py**

In `mcp-proxy/tenants.py`, after line 556 (`MCP_GMAIL_URL = os.getenv(...)`), add:

```python
MCP_MEETING_KB_URL = os.getenv("MCP_MEETING_KB_URL", "http://meeting-kb:8200")
```

- [ ] **Step 2: Add MCPServerConfig to LOCAL_SERVERS**

In `mcp-proxy/tenants.py`, after line 656 (the `scheduler` entry closing brace+comma), add before the closing `}` of LOCAL_SERVERS:

```python
    "meeting-kb": MCPServerConfig(
        server_id="meeting-kb",
        display_name="Meeting Knowledge Base",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_MEETING_KB_URL,
        auth_type="none",
        api_key_env=None,
        description="Search and browse meeting summaries (3 tools)",
        enabled=True,
    ),
```

- [ ] **Step 3: Add to mcp-servers.json**

In `mcp-proxy/config/mcp-servers.json`, add a new entry after the `gmail` entry (before line 136 closing `]`). Note: all tenant groups get access so any user can search meeting summaries:

```json
    {
      "id": "meeting-kb",
      "name": "Meeting Knowledge Base",
      "url": "http://mcp-proxy:8000/meeting-kb",
      "type": "openapi",
      "description": "Search and browse meeting summaries stored in the knowledge base",
      "tier": "local",
      "groups": ["MCP-Admin", "Tenant-Google", "Tenant-Microsoft", "Tenant-AcmeCorp"],
      "api_key_env": null
    }
```

Add a comma after the gmail entry's closing `}` on line 135 before inserting this block.

- [ ] **Step 4: Commit**

```bash
git add mcp-proxy/tenants.py mcp-proxy/config/mcp-servers.json
git commit -m "feat(meeting-kb): register meeting-kb in MCP proxy server registry"
```

---

### Task 5: API Gateway Pass-Through Route

**Files:**
- Modify: `api-gateway/main.py:400-403` (add elif before the generic `/mcp` handler)

- [ ] **Step 1: Add pass-through route**

In `api-gateway/main.py`, add a new `elif` block BEFORE line 401 (`elif full_path.startswith("/mcp")`). The new block intercepts `/mcp/meeting-kb/api/*` and forwards directly to the meeting-kb container:

```python
    # /mcp/meeting-kb/api/* → Meeting KB upload API (bypass MCP Proxy)
    elif full_path.startswith("/mcp/meeting-kb/api"):
        backend_url = os.getenv("MEETING_KB_URL", "http://meeting-kb:8200")
        backend_path = full_path[16:]  # strip "/mcp/meeting-kb" → "/api/..."
    # (existing) /mcp/* → MCP Proxy (tool endpoints) — keep this AFTER the above
    elif full_path.startswith("/mcp"):
```

This must appear BEFORE the generic `/mcp` handler so it takes priority. It falls through to the existing `forward_request()` call — no additional code needed in this branch.

- [ ] **Step 2: Add MEETING_KB_URL to api-gateway environment in docker-compose.unified.yml**

Check if `docker-compose.unified.yml` has an api-gateway service and add `MEETING_KB_URL=http://meeting-kb:8200` to its environment. If the api-gateway uses the same docker-compose.yml, add it there too.

- [ ] **Step 3: Commit**

```bash
git add api-gateway/main.py docker-compose.yml docker-compose.unified.yml
git commit -m "feat(meeting-kb): add API gateway pass-through for upload API"
```

---

### Task 6: Frontend Toggle in Integrations UI

**Files:**
- Modify: `mcp-servers/gdrive/integrations-ui.js:635` (add meeting-kb card after Gmail card)

- [ ] **Step 1: Add Meeting KB icon and card**

In `mcp-servers/gdrive/integrations-ui.js`, after line 635 (`grid.appendChild(gmailCard);`), add the Meeting Knowledge Base card:

```javascript
    // --- Meeting Knowledge Base Card ---
    var MEETING_KB_ICON = '<svg width="28" height="28" viewBox="0 0 24 24" fill="#8e44ad"><path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1c-1.3 0-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm2 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>';
    var MEETING_KB_ICON_SMALL = '<svg width="18" height="18" viewBox="0 0 24 24" fill="#8e44ad"><path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1c-1.3 0-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm2 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>';

    var meetingCard = document.createElement('div');
    meetingCard.setAttribute('data-integration', 'meeting-kb');
    meetingCard.style.cssText = 'background:#2a2a2a;border:1px solid #333;border-radius:12px;padding:16px;transition:all 0.2s;display:flex;align-items:center;gap:14px;';

    var meetingKbEnabled = localStorage.getItem('meeting_kb_enabled') === 'true';

    meetingCard.innerHTML = '<div style="width:44px;height:44px;flex-shrink:0;display:flex;align-items:center;justify-content:center;background:#333;border-radius:10px;padding:8px;">' + MEETING_KB_ICON + '</div>' +
      '<div style="flex:1;min-width:0;">' +
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="color:#fff;font-weight:600;font-size:15px;">Meeting Knowledge Base</span>' +
          '<span id="aiui-status-meeting-kb" style="' + (meetingKbEnabled ? '' : 'display:none;') + 'background:#8e44ad;color:#fff;font-size:11px;padding:2px 10px;border-radius:10px;font-weight:600;">Active</span>' +
        '</div>' +
        '<p style="color:#888;font-size:13px;margin:3px 0 0 0;">Search and browse meeting summaries stored in the knowledge base</p>' +
      '</div>' +
      '<div style="flex-shrink:0;">' +
        '<label style="position:relative;display:inline-block;width:48px;height:26px;cursor:pointer;">' +
          '<input id="aiui-toggle-meeting-kb" type="checkbox" ' + (meetingKbEnabled ? 'checked' : '') + ' style="opacity:0;width:0;height:0;">' +
          '<span style="position:absolute;top:0;left:0;right:0;bottom:0;background:' + (meetingKbEnabled ? '#8e44ad' : '#555') + ';border-radius:26px;transition:0.3s;"></span>' +
          '<span style="position:absolute;top:3px;left:' + (meetingKbEnabled ? '25px' : '3px') + ';width:20px;height:20px;background:#fff;border-radius:50%;transition:0.3s;"></span>' +
        '</label>' +
      '</div>';

    if (meetingKbEnabled) meetingCard.style.borderColor = '#8e44ad';

    meetingCard.addEventListener('mouseenter', function() { meetingCard.style.background = '#333'; });
    meetingCard.addEventListener('mouseleave', function() { meetingCard.style.background = '#2a2a2a'; });

    var meetingToggle = meetingCard.querySelector('#aiui-toggle-meeting-kb');
    meetingToggle.addEventListener('change', function() {
      var enabled = meetingToggle.checked;
      localStorage.setItem('meeting_kb_enabled', enabled ? 'true' : 'false');
      var statusBadge = meetingCard.querySelector('#aiui-status-meeting-kb');
      var slider = meetingToggle.nextElementSibling;
      var knob = slider.nextElementSibling;
      if (enabled) {
        statusBadge.style.display = '';
        slider.style.background = '#8e44ad';
        knob.style.left = '25px';
        meetingCard.style.borderColor = '#8e44ad';
      } else {
        statusBadge.style.display = 'none';
        slider.style.background = '#555';
        knob.style.left = '3px';
        meetingCard.style.borderColor = '#333';
      }
    });

    grid.appendChild(meetingCard);
```

- [ ] **Step 2: Commit**

```bash
git add mcp-servers/gdrive/integrations-ui.js
git commit -m "feat(meeting-kb): add toggle card in integrations UI"
```

---

### Task 7: Environment Variables

**Files:**
- Modify: `.env.example` (add MEETING_KB_API_KEY)

- [ ] **Step 1: Add env vars to .env.example**

Add after the existing MCP-related env vars section:

```bash
# Meeting Knowledge Base
MEETING_KB_API_KEY=             # API key for n8n to upload meeting summaries
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "feat(meeting-kb): add MEETING_KB_API_KEY to .env.example"
```

---

### Task 8: Verification & Smoke Test

- [ ] **Step 1: Verify all files exist**

Run:
```bash
ls -la mcp-servers/meeting-kb/main.py mcp-servers/meeting-kb/Dockerfile mcp-servers/meeting-kb/requirements.txt scripts/migrate-meeting-kb.sql
```
Expected: All 4 files exist.

- [ ] **Step 2: Verify Docker build**

Run:
```bash
docker compose build meeting-kb
```
Expected: Build succeeds.

- [ ] **Step 3: Verify python syntax**

Run:
```bash
python -c "import ast; ast.parse(open('mcp-servers/meeting-kb/main.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Verify mcp-servers.json is valid JSON**

Run:
```bash
python -c "import json; json.load(open('mcp-proxy/config/mcp-servers.json')); print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Document curl commands for n8n**

The n8n HTTP Request node should use:

**Upload single meeting:**
```
POST https://your-domain.com/mcp/meeting-kb/api/meetings
Header: Authorization: Bearer YOUR_MEETING_KB_API_KEY
Header: Content-Type: application/json
Body:
{
  "title": "Sprint Planning - Week 14",
  "summary": "Full meeting notes here...",
  "meeting_date": "2026-04-02T10:00:00Z",
  "participants": ["alice@company.com", "bob@company.com"],
  "tags": ["sprint", "planning"],
  "source": "n8n"
}
```

**Upload bulk:**
```
POST https://your-domain.com/mcp/meeting-kb/api/meetings/bulk
Header: Authorization: Bearer YOUR_MEETING_KB_API_KEY
Header: Content-Type: application/json
Body:
{
  "meetings": [
    { "title": "...", "summary": "...", "meeting_date": "...", "participants": [], "tags": [], "source": "n8n" }
  ]
}
```
