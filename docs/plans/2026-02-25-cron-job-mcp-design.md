# Cron Job MCP Server — Design Document

**Date:** 2026-02-25
**Status:** Approved
**Author:** Justin (with Claude Code)

## Problem

Currently n8n workflows are triggered by events (GitHub webhooks, Discord messages, chat commands). Lukas wants time-based triggers — "every day at 8 PM, check my email" — managed directly from Open WebUI chat.

## Architecture

```
User in Open WebUI chat
    │
    ├─ "Create a cron job that checks n8n workflows every 30 min"
    │
    ▼
MCP Proxy (mcp-proxy:8000)
    │
    ▼
Scheduler MCP Server (mcp-scheduler:8000)  ← NEW container
    │  Tools: create_cron_job, list_cron_jobs, delete_cron_job, trigger_cron_job
    │
    ▼
Webhook Handler API (webhook-handler:8001)  ← EXTENDED
    │  New endpoints: POST/DELETE /scheduler/jobs, PATCH /scheduler/jobs/{id}
    │  Guardrails: min 1min interval (testing), max 10 jobs, 24h auto-expiry
    │
    ▼
APScheduler (already running)
    │
    ▼
n8n API (n8n:5678)
    │  trigger_workflow_by_id() or trigger_workflow(webhook_path)
    │
    ▼
n8n Workflow executes
```

## Approach

**Chosen:** Extend webhook-handler + new MCP tool server (Approach A).

The webhook-handler is the single source of truth for all scheduled jobs. A new MCP server is a thin wrapper that translates chat requests into API calls.

**Rejected alternatives:**
- Approach B (extend n8n MCP server) — third-party image, hard to extend cleanly
- Approach C (pure n8n Schedule Trigger) — no centralized guardrails, scattered visibility

## Webhook-Handler API (New Endpoints)

### Create a cron job
```
POST /scheduler/jobs
{
  "job_id": "check-n8n-every-30min",
  "cron_expression": "*/30 * * * *",
  "workflow_id": "7PDA419IaNb6asSU",
  "trigger_method": "api" | "webhook",
  "webhook_path": "my-webhook",
  "payload": {},
  "description": "Check n8n workflows",
  "permanent": false
}
```

### Delete a cron job
```
DELETE /scheduler/jobs/{job_id}
```

### Update a cron job
```
PATCH /scheduler/jobs/{job_id}
{
  "permanent": true,
  "cron_expression": "0 8 * * *"
}
```

### List all jobs (extended)
```
GET /scheduler/jobs
→ Returns: job_id, cron_expression, next_run, description,
           permanent, expires_at, workflow_id, created_by
```

## Guardrails

| Rule | Value | Reason |
|------|-------|--------|
| Minimum interval | 1 minute (testing), 5 minutes (production) | Prevent runaway jobs |
| Maximum active jobs | 10 user-created (default jobs don't count) | Resource protection |
| Auto-expiry | 24 hours unless `permanent: true` | Forgot-to-turn-off safety net |
| Cron validation | Valid 5-part POSIX format only | Prevent invalid schedules |
| Cleanup task | Hourly check removes expired jobs | Automatic housekeeping |

## MCP Server Tools

New container `mcp-servers/scheduler/` — Python FastAPI wrapped with `mcpo`.

### Tool 1: `create_cron_job`
- Input: `schedule` (human-readable or cron), `workflow_id`, `description`, `permanent`
- Converts human-readable → cron expression
- Calls `POST /scheduler/jobs`
- Returns: confirmation with job_id, next run time, expires_at

### Tool 2: `list_cron_jobs`
- Input: none
- Calls `GET /scheduler/jobs`
- Returns: formatted list of all jobs

### Tool 3: `delete_cron_job`
- Input: `job_id`
- Calls `DELETE /scheduler/jobs/{job_id}`
- Returns: confirmation

### Tool 4: `trigger_cron_job`
- Input: `job_id`
- Calls `POST /scheduler/jobs/{job_id}/trigger`
- Returns: execution result

### Human-Readable Schedule Parsing

| Input | Cron Expression |
|-------|----------------|
| "every 5 minutes" | `*/5 * * * *` |
| "every 30 minutes" | `*/30 * * * *` |
| "every day at 8pm" | `0 20 * * *` |
| "every monday at 9am" | `0 9 * * 1` |
| "every hour" | `0 * * * *` |
| "0 12 * * *" | passed through as-is |

## Docker Integration

```yaml
mcp-scheduler:
  build: ./mcp-servers/scheduler
  environment:
    - WEBHOOK_HANDLER_URL=http://webhook-handler:8001
    - MCP_API_KEY=${MCP_API_KEY}
  networks:
    - internal
  mem_limit: 256m
  mem_reservation: 128m
  restart: unless-stopped
```

## Files Changed

| File | Change |
|------|--------|
| `webhook-handler/scheduler.py` | Add CRUD functions, guardrails, auto-expiry cleanup |
| `webhook-handler/main.py` | Add POST/DELETE/PATCH `/scheduler/jobs` routes |
| `mcp-servers/scheduler/main.py` | NEW — FastAPI app with 4 MCP tools |
| `mcp-servers/scheduler/Dockerfile` | NEW — Python + mcpo wrapper |
| `mcp-servers/scheduler/requirements.txt` | NEW — fastapi, httpx, uvicorn |
| `docker-compose.unified.yml` | Add mcp-scheduler service |
| mcp-proxy config | Register scheduler MCP server |

## Test Plan

1. Create "Cron Test - Hello World" workflow on n8n (webhook trigger, returns timestamp)
2. From chat: "Create a cron job that triggers the test workflow every minute"
3. Verify in n8n Executions tab that it runs every minute
4. Test guardrails: reject <1min, reject 11th job, verify 24h expiry
5. Switch to real schedule (daily/weekly) for production use

## What We're NOT Changing

- Existing default jobs (health report, n8n check)
- n8n MCP server
- Open WebUI or Caddy config
