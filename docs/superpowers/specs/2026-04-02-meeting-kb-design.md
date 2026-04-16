# Meeting Knowledge Base — Design Spec

**Date:** 2026-04-02
**Status:** Approved (rev 2 — post-review fixes)
**Author:** Ralph + Claude

## Overview

A dedicated meeting knowledge base that stores meeting summaries in PostgreSQL (pgvector) and exposes them to AI via an MCP server. When toggled ON, the AI reads ONLY from the `mcp_proxy.meeting_summaries` table — no other data source, no live search, no other container. An HTTP API allows n8n to upload meeting summaries directly.

## Architecture

```
                      Upload path (bypasses MCP Proxy):
n8n ──POST /meeting-kb/api/meetings──▶ API Gateway ──▶ meeting-kb:8200

                      Tool call path (through MCP Proxy):
Open WebUI ──▶ MCP Proxy ──tool call──▶ meeting-kb:8200 ──▶ PostgreSQL
```

**Key routing split:** The HTTP upload API (`/api/meetings*`) is routed directly by the API Gateway to the meeting-kb container, bypassing the MCP Proxy. The MCP tool calls (`search_meetings`, `get_meeting`, `list_meetings`) go through the MCP Proxy as normal.

## 1. Database Layer

All tables live in the existing `mcp_proxy` schema within the shared PostgreSQL instance.

### Table: `mcp_proxy.meeting_summaries`

| Column        | Type           | Notes                              |
|---------------|----------------|------------------------------------|
| id            | UUID (PK)      | Default gen_random_uuid()          |
| title         | VARCHAR(512)   | Meeting title                      |
| summary       | TEXT           | Full meeting summary/notes         |
| meeting_date  | TIMESTAMPTZ    | When the meeting occurred          |
| participants  | TEXT[]         | List of attendees                  |
| tags          | TEXT[]         | Optional categorization            |
| source        | VARCHAR(128)   | Origin: "n8n", "manual", etc.      |
| embedding     | vector(384)    | fastembed BAAI/bge-small-en-v1.5   |
| created_at    | TIMESTAMPTZ    | Default NOW()                      |
| updated_at    | TIMESTAMPTZ    | Default NOW(), trigger on update   |

**Indexes:**
- GIN index on `participants` for array containment queries
- GIN index on `tags` for array containment queries
- **HNSW** index on `embedding` for vector similarity search (works on empty tables, unlike IVFFlat)
- B-tree index on `meeting_date` for date range queries

**Trigger:** `updated_at` auto-updates via a `BEFORE UPDATE` trigger.

### Table: `mcp_proxy.meeting_api_keys`

| Column      | Type           | Notes                        |
|-------------|----------------|------------------------------|
| id          | UUID (PK)      | Default gen_random_uuid()    |
| key_hash    | VARCHAR(128)   | SHA-256 hash of the API key  |
| description | VARCHAR(256)   | Human label for this key     |
| created_at  | TIMESTAMPTZ    | Default NOW()                |

**API key strategy:** The `MEETING_KB_API_KEY` env var is auto-seeded into the `meeting_api_keys` table (hashed) at container startup. All runtime auth checks go through the table. Additional keys can be added to the table later without restarting.

## 2. MCP Server: `meeting-kb`

**Language:** Python 3.11 (FastAPI)
**Port:** 8200
**Image:** python:3.11-slim
**RAM:** ~120MB runtime (fastembed + ONNX Runtime, no PyTorch)

### MCP Tools (exposed via MCP Proxy)

| Tool              | Description                                              |
|-------------------|----------------------------------------------------------|
| `search_meetings` | Semantic search via vector similarity + optional filters (title keyword, date range, participants, tags) |
| `get_meeting`     | Retrieve a specific meeting by UUID                       |
| `list_meetings`   | List recent meetings with pagination (default 20, max 50) |

**Hard constraint:** These tools query ONLY `mcp_proxy.meeting_summaries`. No other table, no external API, no web search.

### HTTP Upload API (for n8n)

| Endpoint                | Method | Auth      | Description                |
|-------------------------|--------|-----------|----------------------------|
| `/api/meetings`         | POST   | API Key   | Upload single summary      |
| `/api/meetings/bulk`    | POST   | API Key   | Upload multiple (max 50)   |
| `/api/meetings/{id}`    | GET    | API Key   | Get a meeting by ID        |
| `/api/meetings/{id}`    | DELETE | API Key   | Delete a meeting           |
| `/health`               | GET    | None      | Health check               |
| `/openapi.json`         | GET    | None      | OpenAPI spec for MCP proxy |

**Authentication:** `Authorization: Bearer <API_KEY>` header, validated against `mcp_proxy.meeting_api_keys` table (SHA-256 hash comparison).

**Bulk limit:** Max 50 meetings per bulk request. Returns 400 if exceeded.

### Embedding Generation

- **Library:** `fastembed` (ONNX Runtime — no PyTorch dependency)
- **Model:** `BAAI/bge-small-en-v1.5` (384 dimensions, matches existing `tool_embeddings.py` pattern)
- Generated server-side on upload — the caller sends plain text, the server computes the embedding
- Used for `search_meetings` semantic similarity via pgvector `<=>` (cosine distance)

## 3. Docker Integration

### New service in `docker-compose.yml`:

```yaml
meeting-kb:
  build: ./mcp-servers/meeting-kb
  container_name: meeting-kb
  restart: unless-stopped
  ports:
    - "8200:8200"
  environment:
    - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD}@postgres:5432/openwebui
    - MEETING_KB_API_KEY=${MEETING_KB_API_KEY}
  depends_on:
    postgres:
      condition: service_healthy
  deploy:
    resources:
      limits:
        memory: 256M
```

No named networks (uses default bridge, consistent with all other services). No volume mounts — all state in PostgreSQL.

### MCP Proxy Registration

**1. Add to `mcp-proxy/config/mcp-servers.json`:**
```json
{
  "id": "meeting-kb",
  "name": "Meeting Knowledge Base",
  "tier": "local",
  "groups": ["MCP-Admin"],
  "api_key_env": null
}
```

**2. Add to `mcp-proxy/tenants.py` LOCAL_SERVERS:**
```python
MCP_MEETING_KB_URL = os.getenv("MCP_MEETING_KB_URL", "http://meeting-kb:8200")

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

**3. Add to mcp-proxy service in `docker-compose.yml`:**
- Environment: `MCP_MEETING_KB_URL=http://meeting-kb:8200`
- depends_on: `meeting-kb` (add to existing depends_on list)

### Routing: API Gateway pass-through

Add a pass-through route in `api-gateway/main.py` for the HTTP upload API:
- Path pattern: `/mcp/meeting-kb/api/*`
- Forwards directly to `http://meeting-kb:8200/api/*` (bypasses MCP Proxy)
- Preserves the `Authorization` header for API key auth
- This is needed because the MCP Proxy is a tool execution proxy, not a transparent HTTP reverse proxy

MCP tool calls (`search_meetings`, etc.) still route normally through the MCP Proxy.

## 4. Frontend Toggle

Add to `integrations-ui.js`:

- New section in integrations modal: **"Meeting Knowledge Base"**
- Simple ON/OFF toggle switch (no OAuth flow needed)
- Toggle state stored in localStorage key: `meeting_kb_enabled`
- When ON: MCP proxy includes `meeting-kb` tools in the AI's available tool list
- When OFF: MCP proxy excludes `meeting-kb` tools — AI cannot see or use them
- Visual indicator: green dot when ON, grey when OFF

## 5. Environment Variables

Add to `.env.example`:
```bash
# Meeting Knowledge Base
MEETING_KB_API_KEY=          # API key for n8n to upload meeting summaries
```

Add to mcp-proxy service environment in `docker-compose.yml`:
```bash
MCP_MEETING_KB_URL=http://meeting-kb:8200
```

## 6. n8n Integration (curl examples)

### Upload a single meeting summary:
```bash
curl -X POST https://your-domain.com/mcp/meeting-kb/api/meetings \
  -H "Authorization: Bearer YOUR_MEETING_KB_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Sprint Planning - Week 14",
    "summary": "Discussed Q2 roadmap priorities. Decided to focus on meeting KB feature first. Alice will handle frontend, Bob takes backend. Target: end of week.",
    "meeting_date": "2026-04-02T10:00:00Z",
    "participants": ["alice@company.com", "bob@company.com"],
    "tags": ["sprint", "planning"],
    "source": "n8n"
  }'
```

### Upload bulk meetings:
```bash
curl -X POST https://your-domain.com/mcp/meeting-kb/api/meetings/bulk \
  -H "Authorization: Bearer YOUR_MEETING_KB_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "meetings": [
      { "title": "...", "summary": "...", "meeting_date": "...", "participants": [], "tags": [] },
      { "title": "...", "summary": "...", "meeting_date": "...", "participants": [], "tags": [] }
    ]
  }'
```

### Response format:
```json
{
  "id": "a1b2c3d4-...",
  "title": "Sprint Planning - Week 14",
  "status": "created",
  "embedding_status": "generated"
}
```

## 7. File Structure

```
mcp-servers/meeting-kb/
  Dockerfile
  requirements.txt
  main.py              # FastAPI app: MCP tools + HTTP upload API
```

## 8. Database Migration

For existing deployments, a migration script is needed since `init-db-hetzner.sql` only runs on fresh DB init:

```
scripts/migrate-meeting-kb.sql    # Run manually on existing deployments
```

The same SQL is also added to `init-db-hetzner.sql` for fresh installs.

## 9. Constraints & Guardrails

- **Data isolation:** The MCP server connects to PostgreSQL but ONLY queries `mcp_proxy.meeting_summaries` and `mcp_proxy.meeting_api_keys`. No ORM — raw SQL with parameterized queries only.
- **No external calls:** No web search, no API calls, no other databases. Pure DB reads.
- **Memory:** ~120MB runtime. fastembed model loads once at startup via ONNX Runtime (no PyTorch).
- **Memory limit:** Docker container capped at 256MB.
- **Security:** API key hashed with SHA-256 before comparison. All SQL parameterized. No user input in query construction.
- **Bulk limit:** Max 50 meetings per bulk upload request.
