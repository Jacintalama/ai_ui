# Google Drive → OpenWebUI Knowledge Base Auto-Sync

**Date:** 2026-03-13
**Status:** Approved
**Approach:** Pure n8n workflow (Approach A)

## Problem

People document things in Google Sheets / Google Drive, but the AI in OpenWebUI can't access that knowledge unless someone manually converts and uploads it. We need automatic ingestion.

## Goal

When a file is uploaded, edited, or deleted in a specific Google Drive folder, it automatically syncs to an OpenWebUI Knowledge Base — making the content searchable via RAG in chat.

## Requirements

| Requirement | Decision |
|-------------|----------|
| Trigger | Poll a specific folder ("AI Knowledge") every 2 min |
| File types | Google Sheets, Docs, Slides, PDFs (skip images/video/archives) |
| Re-sync on edit | Yes — delete old version, re-ingest updated file |
| Delete sync | Yes — file removed from Drive removes it from KB |
| KB organization | Single KB called "Google Drive" |
| Notifications | Discord alert channel for all events |
| File tracking | n8n static data (no extra DB tables) |
| Database | Existing PostgreSQL only (pgvector for embeddings) |
| Google account | aiui.teams@gmail.com |
| Future platforms | Confluence, SharePoint (same pattern, separate KBs) |

## Architecture

```
Google Drive ("AI Knowledge" folder)
  │
  ▼ (poll every 2 min)
n8n Workflow
  │
  ├── NEW/EDIT: Download → Convert to Markdown → Upload to OpenWebUI → Add to KB → Discord notify
  │
  └── DELETE: Lookup in static data → Remove from KB → Discord notify
  │
  ▼
OpenWebUI Knowledge Base ("Google Drive")
  │
  ▼
PostgreSQL (pgvector) — embeddings stored automatically
```

## Markdown Conversion Strategy

| Source Type | Google Export Format | Markdown Conversion |
|-------------|---------------------|---------------------|
| Google Sheets | CSV | Parse CSV → Markdown table with headers |
| Google Docs | HTML | Strip HTML → clean Markdown |
| Google Slides | Plain text | Slide separators + text per slide |
| PDFs | Binary | Upload as-is — OpenWebUI handles PDF natively |
| Other (images, video, zip) | — | Skip — not useful for RAG |

## OpenWebUI API Call Sequence

1. `GET /api/v1/knowledge/` — Find KB by name "Google Drive" (or create if missing)
2. `POST /api/v1/files/` — Upload converted .md file
3. `GET /api/v1/files/{id}/process/status` — Poll until "completed" (max 10 attempts, 3s interval)
4. `POST /api/v1/knowledge/{kb_id}/file/add` — Add processed file to KB
5. Discord notification via bot API

## File Tracking (n8n Static Data)

No extra database tables. n8n's built-in static data stores the mapping:

```json
{
  "gdrive_abc123": {
    "openwebui_file_id": "file_xyz",
    "filename": "Q1 Users.gsheet",
    "last_modified": "2026-03-13T10:00:00Z"
  }
}
```

## n8n Workflow Nodes (~14 nodes)

| # | Node | Type | Purpose |
|---|------|------|---------|
| 1 | Google Drive Trigger | googleDriveTrigger | Poll folder every 2 min |
| 2 | Find or Create KB | httpRequest | GET/POST OpenWebUI KB |
| 3 | Switch by Event | switch | Route: new / edit / delete |
| 4 | Download File | googleDrive | Export file content |
| 5 | Convert to Markdown | code | JS: CSV→table, HTML→MD |
| 6 | Check if Edit | if | If edit → delete old first |
| 7 | Delete Old File | httpRequest | Remove previous version from KB |
| 8 | Upload to OpenWebUI | httpRequest | POST /api/v1/files/ |
| 9 | Poll Processing | httpRequest + loop | Wait for embedding completion |
| 10 | Add to KB | httpRequest | POST /knowledge/{id}/file/add |
| 11 | Update Static Data | code | Save gdrive-openwebui mapping |
| 12 | Lookup for Delete | code | Find file in static data |
| 13 | Remove from KB | httpRequest | Delete file from KB |
| 14 | Discord Notify | httpRequest | Send notification |

## Error Handling

| Error | Action |
|-------|--------|
| Google Drive API fails | Retry on next poll cycle (2 min) |
| OpenWebUI upload fails | Retry once, then Discord error notification |
| File processing stuck | After 30s polling → skip, Discord error |
| KB not found & create fails | Discord error, workflow stops |
| Discord notification fails | Log only, don't block pipeline |

## Components Touched

| Component | Change |
|-----------|--------|
| n8n | New workflow (~14 nodes) |
| docker-compose.unified.yml | Add DISCORD_BOT_TOKEN + DISCORD_ALERT_CHANNEL_ID to n8n env |
| OpenWebUI | No changes — uses existing API |
| PostgreSQL | No changes — no new tables |
| Google Drive | Create "AI Knowledge" folder |
| n8n credentials | May need Google Drive OAuth credential |

## What We're NOT Building

- No new containers
- No new Python code
- No webhook-handler changes
- No new database tables
- No Caddy/routing changes
