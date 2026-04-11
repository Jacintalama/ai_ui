# Meeting Container Design

**Date:** 2026-04-03
**Status:** Approved
**Approach:** Standalone FastAPI container (`mcp-meetings`)

## Problem

The team needs a dedicated service to store Fathom meeting data (summaries, transcripts, links) and make it searchable via OpenWebUI Knowledge Base. Currently meetings are only saved to Google Sheets and Discord — no queryable API or KB integration.

## Goal

A new `mcp-meetings` container that stores meeting records in PostgreSQL and auto-pushes them to OpenWebUI KB so users can ask questions about past meetings.

## Architecture

### Container Structure

```
mcp-servers/meetings/
├── Dockerfile
├── main.py          # FastAPI app with endpoints
├── models.py        # SQLAlchemy models (meetings schema)
├── kb_sync.py       # OpenWebUI KB auto-push logic
└── requirements.txt
```

Follows the same pattern as `mcp-calendar`, `mcp-gdrive`, etc. FastAPI on port 8000, connected to shared PostgreSQL.

### Docker Compose

- Image: built from `mcp-servers/meetings/`
- Network: `backend`
- Memory limit: `128M`
- Depends on: `postgres`
- Env vars: `DATABASE_URL`, `OPENWEBUI_URL`, `OPENWEBUI_API_KEY`

### Caddy Route

`/meetings/*` → `mcp-meetings:8000`

## Database Schema

New `meetings` schema in shared PostgreSQL:

```sql
CREATE SCHEMA IF NOT EXISTS meetings;

CREATE TABLE meetings.records (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         VARCHAR(500) NOT NULL,
    date          TIMESTAMP NOT NULL,
    attendees     TEXT,
    summary       TEXT,
    transcript    TEXT,
    fathom_link   VARCHAR(1000),   -- null if not available
    action_items  TEXT,
    kb_file_id    VARCHAR(100),    -- OpenWebUI file ID after KB push
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
```

- `fathom_link` — nullable. Null if not available, stored if provided.
- `kb_file_id` — tracks which OpenWebUI KB file this meeting maps to (for updates/deduplication)
- Auto-created on container startup via SQLAlchemy

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST /meetings` | Save a new meeting (n8n sends data here) |
| `GET /meetings` | List meetings (optional filters: date range, search) |
| `GET /meetings/{id}` | Get a specific meeting |
| `PUT /meetings/{id}` | Update a meeting (e.g. add fathom_link later) |
| `DELETE /meetings/{id}` | Delete a meeting |
| `GET /health` | Health check |

### POST /meetings Flow

1. n8n sends JSON: `{ title, date, attendees, summary, transcript, fathom_link, action_items }`
2. Container saves to `meetings.records` table
3. Container auto-pushes to OpenWebUI KB (background task)
4. Saves `kb_file_id` back to the record
5. Returns `201` with the meeting record

### PUT /meetings/{id} Flow

- If `fathom_link` is updated from null to a value, re-pushes to KB with the link included

## OpenWebUI KB Auto-Push

When a meeting is saved, the container:

1. Formats the meeting as markdown:

```markdown
# {title}
Date: {date} | Attendees: {attendees}

## Summary
{summary}

## Action Items
{action_items}

## Transcript
{transcript}

## Recording
{fathom_link or "No recording link available"}
```

2. Uploads to OpenWebUI via existing API pattern:
   - `POST /api/v1/files/` — upload markdown file
   - Poll `/api/v1/files/{file_id}/process/status` until completed
   - `POST /api/v1/knowledge/{kb_id}/file/add` — add to "Meeting Transcripts" KB

3. If the KB doesn't exist yet, auto-creates it (same pattern as `mcp-servers/web-search/main.py`)

4. KB push runs as a background task — API returns immediately, KB upload happens async. If it fails, meeting is still saved in DB (`kb_file_id` stays null).

## Data Flow

```
n8n HTTP Request → POST /meetings → Save to DB → Auto-push to KB
                                                        ↓
                                          OpenWebUI "Meeting Transcripts" KB
                                                        ↓
                                          Users ask: "What did we discuss about X?"
```

## What Does NOT Get Built (YAGNI)

- No Discord command integration (add later if needed)
- No n8n workflow changes (Clarence adds the HTTP request node when ready)
- No authentication on the API (internal network only, same as other MCP containers)
- No scheduled/cron jobs
