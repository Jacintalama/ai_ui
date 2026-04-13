# Design: Claude Desktop Connection, Google Calendar, Fathom Transcripts

**Date:** 2026-03-27
**Author:** Jacint Alama
**Status:** Approved

## Overview

Connect our MCP proxy server to Claude Desktop so all 4 team members can use 40+ tools from their local Claude Desktop app. Add Google Calendar integration for standup scheduling. Automate Fathom meeting transcript processing.

## Architecture

Hub-and-spoke pattern. MCP Proxy is the hub. Clients (Claude Desktop, Discord, Open WebUI) are spokes. MCP servers (Gmail, Calendar, GitHub, etc.) are backend spokes.

```
Claude Desktop (4 users) ──┐
Discord Bot                ──┼──► Caddy ──► MCP Auth ──► MCP Proxy ──► Gmail
Open WebUI                 ──┘                                      ──► Calendar (NEW)
                                                                    ──► GitHub
                                                                    ──► Web Search
                                                                    ──► 30+ more
```

## Task 1: Claude Desktop Connection

### Problem
MCP proxy is only accessible internally (behind API Gateway + JWT auth). Claude Desktop needs an external endpoint with API key auth.

### Solution
Expose MCP proxy via new Caddy route with per-user API key authentication.

**New Caddy route:**
```
ai-ui.coolestdomain.win/mcp-remote/* → MCP Auth Middleware → MCP Proxy
```

**Auth flow:**
1. Claude Desktop sends `POST /mcp-remote/mcp` with `Authorization: Bearer <api-key>`
2. Caddy forwards to MCP Auth Middleware
3. Middleware validates API key against PostgreSQL, injects `X-User-Email` and `X-User-Groups`
4. MCP Proxy routes to correct tool (existing logic, no changes)

**Per-user API keys (PostgreSQL table `mcp_api_keys`):**

| user_email | api_key | groups | created_at |
|---|---|---|---|
| lukas@straightforwardllc.us | sk-lukas-xxxx | MCP-Admin | 2026-03-27 |
| ralphbenitez30@gmail.com | sk-ralph-xxxx | MCP-Admin | 2026-03-27 |
| alamajacintg04@gmail.com | sk-jacint-xxxx | MCP-Admin | 2026-03-27 |
| clidebacalla@gmail.com | sk-clarenz-xxxx | MCP-Admin | 2026-03-27 |

**Claude Desktop config (each user adds to their claude.json):**
```json
{
  "mcpServers": {
    "aiui": {
      "type": "streamableHttp",
      "url": "https://ai-ui.coolestdomain.win/mcp-remote/mcp",
      "headers": {
        "Authorization": "Bearer sk-<user>-xxxx"
      }
    }
  }
}
```

### Components
- **MCP Auth Middleware** — lightweight FastAPI app (or extend existing API Gateway). Validates Bearer token, looks up user, injects headers, proxies to MCP Proxy.
- **Caddy route** — `/mcp-remote/*` bypasses API Gateway, goes directly to auth middleware.
- **DB table** — `mcp_api_keys` stores hashed API keys + user mapping.

## Task 3: Google Calendar MCP Server

### Problem
Gmail MCP server can send emails but cannot create calendar events or send meeting invites. Lukas wants automated standup scheduling.

### Solution
New `mcp-calendar` Docker container. Reuses existing Google OAuth infrastructure from `mcp-gmail`. Uses shared `aiui.teams@gmail.com` account.

**New Google OAuth scope:** `https://www.googleapis.com/auth/calendar.events`

### Tools (5)

| Tool | Endpoint | Purpose |
|---|---|---|
| `calendar_create_event` | `POST /calendar_create_event` | Create event with title, time, attendees, recurrence, Google Meet link |
| `calendar_list_events` | `POST /calendar_list_events` | List upcoming events for a date range |
| `calendar_send_invite` | `POST /calendar_send_invite` | Create event + send email invites to all attendees |
| `calendar_update_event` | `POST /calendar_update_event` | Reschedule or modify existing event |
| `calendar_delete_event` | `POST /calendar_delete_event` | Cancel event and notify attendees |

### Key Parameters

**calendar_create_event / calendar_send_invite:**
```json
{
  "title": "AIUI Team Standup",
  "start_time": "2026-03-28T21:30:00+08:00",
  "duration_minutes": 30,
  "description": "Daily team standup",
  "attendees": [
    "lukas@straightforwardllc.us",
    "ralphbenitez30@gmail.com",
    "alamajacintg04@gmail.com",
    "clidebacalla@gmail.com"
  ],
  "recurrence": "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,TH,FR",
  "add_google_meet": true
}
```

### Standup Schedule
- **9:30 PM PHT** Mon/Wed/Thu/Fri — `RRULE:FREQ=WEEKLY;BYDAY=MO,WE,TH,FR`
- **8:30 PM PHT** Tuesday — `RRULE:FREQ=WEEKLY;BYDAY=TU`

### Docker Setup
- Container: `mcp-calendar` (port 8000, backend network)
- Base: Same as `mcp-gmail` (FastAPI + Google OAuth)
- Token storage: PostgreSQL `calendar_tokens` table (or reuse `gmail_tokens` if same account)
- Registered in `tenants.py` as LOCAL server with `auth_type: "none"`

## Task 4: Fathom Transcript Processing

### Problem
Team uses Fathom for meeting transcription. Recordings are emailed after each meeting. Currently manual — need to auto-process transcripts into summaries, action items, and searchable KB.

### Solution
n8n workflow triggered by Fathom emails arriving in `aiui.teams@gmail.com`.

### Workflow

```
Fathom email arrives at aiui.teams@gmail.com
    ↓
n8n Gmail Trigger (polls for emails from Fathom / subject contains "recording")
    ↓
Extract transcript from email body or linked page
    ↓
Claude API: Summarize + extract action items
    ↓
Save full transcript + summary to Open WebUI KB ("Meeting Transcripts")
    ↓
Post summary to Discord #general channel
```

### Output Per Meeting
- **Summary** — 3-5 bullet points
- **Action items** — who does what, with names
- **Full transcript** — saved to KB for future queries
- **Discord notification** — summary posted to #general

### Future Queries
Team can ask in Claude Desktop or Open WebUI:
- "What did we discuss in yesterday's standup?"
- "What are my action items from last week?"
- "Has Lukas mentioned anything about the calendar feature?"

## Team Members

| Name | Email | Role |
|---|---|---|
| Lukas | lukas@straightforwardllc.us | Product owner |
| Ralph | ralphbenitez30@gmail.com | Dev — scheduling, Gmail, triggering |
| Jacint | alamajacintg04@gmail.com | Dev — proxy server, technical backend |
| Clarenz | clidebacalla@gmail.com | Dev — transcription, Fathom setup |

## Implementation Order

1. **Task 1: Claude Desktop connection** (Jacint) — MCP auth middleware, Caddy route, API keys
2. **Task 3: Google Calendar MCP server** (Jacint + Ralph) — new container, 5 tools, OAuth scope
3. **Task 4: Fathom workflow** (Ralph + Clarenz) — n8n workflow, email trigger, KB save

## Dependencies

- Task 3 depends on Task 1 (Calendar tools need to be accessible from Claude Desktop)
- Task 4 is independent (can be built in parallel)
- Google Calendar API scope must be added in Google Cloud Console (AIUI Project)
