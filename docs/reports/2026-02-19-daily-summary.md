# AIUI Platform — Daily Summary Report
**Date:** February 19, 2026
**Branch:** `fix/mcp-network-split`

---

## Executive Summary

The AIUI platform is a **multi-tenant AI workspace** with 30+ integrated tools, deployed on a Hetzner VPS. Today's work focused on adding **slash command support** (Slack + Discord), building an **end-of-day report feature**, and fixing bugs found during live testing.

**Key numbers:**
- **15 containers** running in Docker Compose
- **232 MCP tools** cached and available
- **12 webhook endpoints** for external integrations
- **4 automation patterns** (event-driven, chat-driven, scheduled, reporting)
- **5 security layers** (TLS, JWT, rate limiting, signature verification, group ACL)
- **4 users**, **7 groups**, **3 tenants** configured

---

## Architecture Overview

```
Browser → Cloudflare → Caddy (port 80) → API Gateway (8080) → Backend Services
                             ↓
                  Bypasses for: webhooks, n8n, static assets, WebSocket
```

### Core Services

| Service | Role | Port |
|---|---|---|
| **Caddy** | Reverse proxy, TLS termination (Let's Encrypt) | 80/443 |
| **API Gateway** | JWT validation (HS256), rate limiting (500/min per user), header injection | 8080 |
| **Open WebUI** | AI chat interface (70+ LLM models) | 8080 |
| **MCP Proxy** | Multi-tenant tool orchestration (232 tools, 44 servers) | 8000 |
| **Admin Portal** | User/group management UI at `/mcp-admin` | 8080 |
| **Webhook Handler** | External event processing (GitHub, Slack, Discord, n8n) | 8086 |
| **n8n** | Workflow automation engine (hosted at `n8n.srv1041674.hstgr.cloud`) | 5678 |
| **PostgreSQL** | Database (pgvector-enabled for semantic search) | 5432 |
| **Redis** | Sessions and cache | 6379 |

### MCP Tool Servers (9 containers)

| Server | Tools | What It Does |
|---|---|---|
| GitHub | 26 | Repo management, PRs, issues, code search |
| Filesystem | 14 | File read/write/search on server |
| ClickUp | 177+ | Task management |
| Trello | — | Kanban boards |
| SonarQube | — | Code quality analysis |
| Excel Creator | — | Spreadsheet generation |
| Dashboard | — | Executive dashboard generation |
| Notion | — | Workspace and documentation access |
| n8n MCP | ~20 | AI-driven workflow management (list, create, execute workflows) |

---

## What Was Built Today (Feb 19)

### 1. Slash Commands — Slack & Discord (`/aiui`)

Both platforms share a **CommandRouter** (`handlers/commands.py`) for platform-agnostic command processing.

**Pattern:** Acknowledge immediately (< 3 seconds) → process in background via `asyncio.create_task()` → send result via platform-specific callback.

| Command | What It Does |
|---|---|
| `/aiui ask <question>` | Sends question to AI via Open WebUI, returns response |
| `/aiui workflow <name>` | Triggers an n8n workflow by webhook path |
| `/aiui report` | Generates end-of-day report with AI summary |
| `/aiui status` | Checks health of all 4 core services |
| `/aiui help` | Shows available commands |

**Slack-specific:**
- Endpoint: `POST /webhook/slack/commands`
- Auth: HMAC-SHA256 signature verification (`SLACK_SIGNING_SECRET`)
- Payload: `application/x-www-form-urlencoded` (NOT JSON)
- Response: Posts result to Slack's `response_url` (pre-authenticated, no token needed)

**Discord-specific:**
- Endpoint: `POST /webhook/discord`
- Auth: Ed25519 signature verification (`DISCORD_PUBLIC_KEY`, via PyNaCl)
- Payload: JSON
- Response: Returns deferred (type 5), then edits original message via `PATCH /webhooks/{app_id}/{token}/messages/@original`
- PING/PONG: Type 1 must return type 1 or Discord disables the endpoint

### 2. End-of-Day Report (`/aiui report`)

Gathers data from 3 sources in parallel, sends to AI for summarization:

```
/aiui report
    ├── GitHub Commits (today) → via GITHUB_TOKEN + REPORT_GITHUB_REPO
    ├── n8n Executions (today) → via N8N_API_KEY + n8n API
    └── Service Health (live)  → hits 4 health endpoints
            ↓
    AI Summarization (via Open WebUI)
            ↓
    Reply to user + optional Slack channel post (REPORT_SLACK_CHANNEL)
```

**Graceful degradation:**
- If `GITHUB_TOKEN` not set → skips GitHub data, reports "unavailable"
- If `N8N_API_KEY` not set → skips n8n data, reports "unavailable"
- If AI fails (e.g., quota exceeded) → falls back to raw data dump
- If `REPORT_SLACK_CHANNEL` not set → only replies to requesting user

### 3. Bug Fixes

| Bug | Root Cause | Fix |
|---|---|---|
| n8n webhook empty body crash | n8n returns HTTP 200 with empty body; `response.json()` throws | Check `response.text.strip()` before parsing; default to `{"status": "ok"}` |
| Stale n8n_url default | `config.py` defaulted to `http://n8n:5678` (local container) | Changed default to `https://n8n.srv1041674.hstgr.cloud` (hosted instance) |
| Dead import in report handler | Unused import from earlier refactor | Removed |
| n8n workflow names unresolved | Executions API doesn't always include workflow name | Pre-fetch `/api/v1/workflows` for ID-to-name mapping |

---

## Automation Patterns

The platform supports 4 complementary automation patterns:

### 1. Event-Driven (Webhooks)
```
GitHub push/PR  →  /webhook/github  →  n8n workflow  →  AI review + GitHub comment + Slack notification
Slack @mention  →  /webhook/slack   →  AI response   →  Slack reply
```

### 2. Chat-Driven (Slash Commands)
```
/aiui ask|workflow|status  →  CommandRouter  →  AI response / n8n trigger / health check
Works from both Slack and Discord (same CommandRouter)
```

### 3. Scheduled (Cron via APScheduler)
```
daily_health_report()         →  checks 4 services, posts to Slack (noon daily)
hourly_n8n_workflow_check()   →  lists n8n workflows (every hour)
```

### 4. Reporting (Data Aggregation + AI)
```
/aiui report  →  gathers GitHub + n8n + health  →  AI summary  →  reply + Slack post
```

---

## Security Architecture

```
Layer 1: TLS          — Caddy auto-HTTPS via Let's Encrypt
Layer 2: JWT          — API Gateway validates HS256 tokens (cookie or Bearer header)
Layer 3: Rate Limit   — 500/min per user, 5000/min per IP (sliding window)
Layer 4: Signatures   — GitHub (HMAC-SHA256), Slack (v0 HMAC), Discord (Ed25519)
Layer 5: Group ACL    — MCP Proxy enforces group-based tool access from PostgreSQL
```

| Layer | Enforced By | Failure Mode |
|---|---|---|
| TLS | Caddy | Connection refused |
| JWT validation | API Gateway | Empty user context (unauthenticated) |
| Rate limiting | API Gateway | `429 Too Many Requests` |
| Signature verification | Webhook Handler | `401 Unauthorized` |
| Group-based ACL | MCP Proxy | `403 Access Denied` |

---

## n8n Workflows (Hosted Instance)

| Workflow | Trigger | What It Does |
|---|---|---|
| **PR Review Automation** | Webhook (6 nodes) | PR data → AI code review → GitHub comment → Slack notification |
| **GitHub Push Processor** | Webhook (5 nodes) | Push data → commit summary → Slack notification |

Additionally, the **MCP n8n server** (`czlonkowski/n8n-mcp`) provides ~20 tools for managing n8n workflows directly from the AI chat interface.

---

## MCP Admin Portal State

| Tab | Current Data |
|---|---|
| Users & Groups | 4 users (alamajacintg04, github@test.com, kimcalicoy24, lherajt) |
| Groups & Servers | 7 groups (MCP-Admin, MCP-Excel, MCP-Filesystem, MCP-GitHub, Tenant-AcmeCorp, Tenant-Google, Tenant-Microsoft) |
| API Keys | 1 key (GITHUB_TOKEN for MCP-GitHub group) |
| Dynamic Routing | No overrides configured |
| MCP-Admin group | 10 servers enabled (atlassian, excel, filesystem, github, gitlab, hubspot, linear, n8n, notion, slack) |

**MCP Proxy health:** 232 tools cached, 3 tenants active.

---

## Deployment

**Infrastructure:** Single Hetzner VPS at `ai-ui.coolestdomain.win`
**Stack:** Docker Compose (`docker-compose.unified.yml`) — 15 containers
**Traffic:** Browser → Cloudflare → Caddy → API Gateway → Backends
**Compose command:** `docker compose -f docker-compose.unified.yml up -d`
**Rebuild single service:** `docker compose -f docker-compose.unified.yml up -d --build <service>`

---

## Webhook Endpoints (Complete List)

| Endpoint | Method | Source | Auth |
|---|---|---|---|
| `/webhook/github` | POST | GitHub | HMAC-SHA256 |
| `/webhook/slack` | POST | Slack Events API | Slack HMAC v0 |
| `/webhook/slack/commands` | POST | Slack Slash Commands | Slack HMAC v0 |
| `/webhook/discord` | POST | Discord Interactions | Ed25519 |
| `/webhook/n8n/{path}` | POST | Any (forwarding) | None |
| `/webhook/mcp/{server}/{tool}` | POST | Any | None |
| `/webhook/automation` | POST | Any | None |
| `/webhook/generic` | POST | Any | None |
| `/scheduler/jobs` | GET | Internal | None |
| `/scheduler/jobs/{id}/trigger` | POST | Internal | None |
| `/scheduler/health-report` | GET | Internal | None |
| `/scheduler/n8n-check` | GET | Internal | None |

---

## Git History (Today's Commits)

```
b2a5742 fix: resolve n8n workflow names from workflowId in executions API
53aa664 fix: remove dead import in _handle_report
cf01bfd feat: add /aiui report command with AI-summarized daily reports
83fb327 docs: add deep research findings and EOD report implementation plan
228704d docs: add end-of-day report command design
e61511e docs: update architecture guides with slash commands, n8n, and automation patterns
805ad9d docs: add standup notes for 2026-02-18
050c58f feat: add Discord slash command endpoint with Ed25519 verification
7bba448 feat: add Slack slash command endpoint with async processing
3539e0b feat: add shared CommandRouter for slash commands
1a88958 fix: default n8n_url to hosted instance, prevent split-brain
```

---

## Key Files

```
IO/
├── docker-compose.unified.yml       # Production stack (15 containers)
├── Caddyfile                        # Reverse proxy routing rules
├── .env                             # Credentials (DO NOT commit)
├── api-gateway/main.py              # JWT validation, rate limiting, request forwarding
├── mcp-proxy/main.py                # Multi-tenant tool gateway (232 tools)
├── webhook-handler/
│   ├── main.py                      # FastAPI app, 12 endpoints
│   ├── config.py                    # Settings from .env (21 variables)
│   ├── scheduler.py                 # APScheduler cron jobs
│   ├── handlers/
│   │   ├── commands.py              # Shared CommandRouter (Slack + Discord)
│   │   ├── github.py                # GitHub event handler
│   │   ├── slack.py                 # Slack Events API handler
│   │   ├── slack_commands.py        # Slack slash commands
│   │   ├── discord_commands.py      # Discord slash commands
│   │   ├── mcp.py                   # MCP tool executor
│   │   ├── automation.py            # AI + MCP automation pipe
│   │   └── generic.py               # Generic JSON → AI analysis
│   └── clients/
│       ├── openwebui.py             # AI chat completions
│       ├── github.py                # GitHub API (comments, PRs, commits)
│       ├── slack.py                 # Slack messages + response_url
│       ├── discord.py               # Discord followup/edit messages
│       ├── n8n.py                   # n8n workflow triggering + executions
│       └── mcp_proxy.py             # MCP tool execution
└── docs/
    ├── architecture-guide.md        # Full architecture documentation
    ├── ARCHITECTURE.md              # Quick reference
    └── webhook-architecture.md      # Webhook-specific docs
```

---

## Known Issues

| Issue | Impact | Resolution |
|---|---|---|
| **OpenAI API quota exhausted** | All AI-dependent features return 429 errors | Top up billing at `platform.openai.com` — not a code bug |
| **Slack/Discord not yet configured** | Slash commands return 503 (dormant) | Lukas needs to configure apps + set env vars on server |
| **REPORT_SLACK_CHANNEL not set** | Report only replies to user, doesn't post to channel | Set env var when Slack channel is decided |

---

## Next Steps for Lukas

1. **Fix OpenAI quota** — Top up at `platform.openai.com` to restore AI features
2. **Configure Slack App** — Add `/aiui` slash command pointing to `https://ai-ui.coolestdomain.win/webhook/slack/commands`
3. **Configure Discord App** — Create app, set interactions URL to `https://ai-ui.coolestdomain.win/webhook/discord`, set env vars
4. **Set `REPORT_SLACK_CHANNEL`** — Channel ID where daily reports should be posted
5. **Push to GitHub** — Local changes not yet pushed (per Lukas's instruction)
