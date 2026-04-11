# Fathom Meeting → OpenWebUI Knowledge Base Integration

**Date:** 2026-04-02
**Status:** Approved
**Author:** Jacint Alama

## Problem

Fathom meeting transcripts are saved to Google Sheets and posted to Discord, but they're not searchable by the AI. Team members can't ask "What did we discuss about voice bot?" and get an answer with the recording link.

## Solution

Add KB saving as a third parallel output to the existing Fathom n8n workflow. No new containers — uses OpenWebUI's built-in Knowledge Base API with PGVector embeddings.

## Architecture

```
Fathom Email → Gmail Trigger → Parse Fathom Email
                                      ↓
                          ┌───────────┼───────────┐
                          ↓           ↓           ↓
                    Google Sheets  Discord    Save to KB
                    (audit trail) (notify)   (RAG search)
```

### KB Save Flow (3 n8n nodes)

1. **Format as Markdown** (Code node) — Converts parsed meeting data into a structured Markdown document with title, date, attendees, summary sections, action items, and Fathom recording link.

2. **Upload to OpenWebUI** (HTTP Request node) — `POST /api/v1/files/` with multipart form-data. Polls `GET /api/v1/files/{id}/process/status` until embedding completes (max 30 retries, 2s interval).

3. **Add to KB** (HTTP Request node) — `POST /api/v1/knowledge/{kb_id}/file/add` to associate the processed file with the "Meeting Transcripts" knowledge base.

### KB Document Format

```markdown
# {Meeting Title}
Date: {date} | Duration: {duration} | Attendees: {attendees}

## Meeting Purpose
{purpose section from summary}

## Key Takeaways
{takeaways from summary}

## Topics
{topics from summary}

## Action Items
{action items with assignees}

## Recording
{fathom_link}
```

### Components

| Component | Purpose | New? |
|-----------|---------|------|
| OpenWebUI KB API | File storage + PGVector embedding | Exists |
| "Meeting Transcripts" KB | Collection for all meetings | Create once |
| Format Markdown node | Code node in n8n workflow | New |
| Upload + Poll node | HTTP Request with retry | New |
| Add to KB node | HTTP Request | New |

### Authentication

- Bearer token using `WEBUI_SECRET_KEY` (already in .env on server)
- Same auth pattern used by gdrive-knowledge-sync and web-search workflows

### Deduplication

- Track processed email IDs in workflow static data (`$getWorkflowStaticData('global')`)
- Skip emails already saved to KB
- Prevents duplicates on workflow restarts or re-polls

### Error Handling

- KB upload failure does NOT block Sheets or Discord (parallel branches)
- Polling timeout after 30 retries → log warning, skip KB save
- File processing failure → skip, continue with next email

### Query Patterns (how users search)

| Interface | How |
|-----------|-----|
| AIUI web chat | "What did we discuss about voice bot?" → RAG search → returns summary + link |
| Discord (future) | Same query via webhook-handler → OpenWebUI chat completions API |
| Claude Desktop (future) | Via MCP proxy → same OpenWebUI KB |

## Constraints

- No Kubernetes — Docker Compose only
- No new containers — OpenWebUI handles KB storage
- Server has 3.8GB RAM — KB files are small text (< 10KB each)
- n8n is on cloud (not in docker-compose.unified.yml) — HTTP calls to OpenWebUI must use the public URL or be routed through Caddy

## Open Questions

- n8n Cloud → OpenWebUI: need to confirm n8n can reach OpenWebUI at `https://ai-ui.coolestdomain.win/api/v1/` (through Caddy + API Gateway)
- Bearer token: may need to generate an API key in OpenWebUI admin panel rather than using WEBUI_SECRET_KEY directly
- KB size over time: ~1 meeting/day × ~5KB = ~1.8MB/year, negligible

## Reference Implementations

- `mcp-servers/web-search/main.py` (lines 165-253) — `_get_or_create_kb()` and `_upload_file_to_kb()` patterns
- `n8n-workflows/gdrive-knowledge-sync.json` — Full KB CRUD workflow
- `n8n-workflows/fathom-transcript-processor.json` — Earlier Fathom → KB attempt (reference for node structure)
