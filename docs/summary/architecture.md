# IO Platform — Full System Architecture

> **Last updated:** 2026-03-09
> **Domain:** ai-ui.coolestdomain.win
> **Server:** Hetzner VPS (3.8 GB RAM) at 46.224.193.25
> **Stack:** Docker Compose on Linux, 20+ containers

---

## How It All Connects (Big Picture)

```
                          INTERNET
                             |
                        [ Cloudflare ]
                             |
                        [ Caddy :80 ]
                             |
            +----------------+----------------+------------------+
            |                |                |                  |
     /webhook/*        /n8n/*          /grafana/*         Everything else
            |                |                |                  |
   webhook-handler     n8n:5678       grafana:3000      API Gateway :8080
       :8086                                                     |
                                                    +------------+------------+
                                                    |                         |
                                              Open WebUI              MCP Proxy
                                                :8080                   :8000
                                                    |                     |
                                              [ Postgres ]         [ MCP Servers ]
                                              [ Redis    ]         (14 tool servers)
```

---

## All Services At a Glance

| Service | Port | What It Does |
|---------|------|-------------|
| **Caddy** | 80, 443 | Reverse proxy, TLS, routes all traffic |
| **API Gateway** | 8080 | JWT auth, rate limiting, user header injection |
| **Open WebUI** | 8080 | AI chat interface, LLM frontend |
| **Webhook Handler** | 8086 | GitHub/Slack/Discord/n8n webhook processing, slash commands |
| **PR Reviewer** | 3000 | Claude Code CLI sandbox for PR reviews |
| **n8n** | 5678 | Workflow automation engine |
| **MCP Proxy** | 8000 | Multi-tenant tool gateway (14 MCP servers behind it) |
| **Postgres** | 5432 | Database (users, groups, vectors, analytics) |
| **Redis** | 6379 | Sessions, cache |
| **Pipelines** | 9099 | External pipe/filter runner |
| **Loki** | 3100 | Log aggregation (7-day retention) |
| **Promtail** | 9080 | Log shipper (auto-discovers all containers) |
| **Grafana** | 3000 | Dashboards, alerts, log explorer |
| **Admin Portal** | 8080 | User/group/server management UI |

**MCP Tool Servers (each on port 8000/8001):**

| Server | Tools | Purpose |
|--------|-------|---------|
| mcp-github | 26 | GitHub repos, issues, PRs, search |
| mcp-filesystem | 14 | Sandboxed file operations |
| mcp-excel | 14 | Excel spreadsheet generation |
| mcp-clickup | 177+ | ClickUp task management |
| mcp-trello | — | Trello boards |
| mcp-sonarqube | — | Code quality analysis |
| mcp-notion | — | Notion workspace/docs |
| mcp-n8n | 20 | n8n workflow management |
| mcp-scheduler | — | Cron job management |
| mcp-dashboard | — | Executive dashboard generation |

---

## Traffic Flow: Browser to App

```
User opens ai-ui.coolestdomain.win
        |
   Cloudflare (CDN, DDoS protection)
        |
   Caddy (reverse proxy)
        |
        +-- Static assets (_app/*, /static/*, /favicon, /ws/*)
        |       |
        |       +---> open-webui:8080  (BYPASSES Gateway — avoids rate limit 429s)
        |
        +-- All other routes (/, /mcp/*, /admin/*)
                |
           API Gateway :8080
                |
                +-- Validates JWT (from cookie or Authorization header)
                +-- Rate limits (500/min per user, 5000/min per IP)
                +-- Injects headers: X-User-Email, X-User-Groups, X-User-Admin
                |
                +-- /mcp/*, /admin/* ---> MCP Proxy :8000
                +-- Everything else ---> Open WebUI :8080
```

**Why static assets bypass the gateway:** Open WebUI loads 60+ JS/CSS files on page load. If those hit the rate limiter, everything 429s and the page goes blank.

---

## How GitHub Webhooks Work

```
GitHub sends webhook (push, PR, issue, comment)
        |
   POST /webhook/github
        |
   Caddy --> webhook-handler:8086
        |
   Verify HMAC-SHA256 signature (GITHUB_WEBHOOK_SECRET)
        |
   Route by event type:
        |
        +-- "pull_request" (opened/synchronize)
        |       |
        |       +-- 1. Try Claude Code review (pr-reviewer:3000)
        |       |       |
        |       |       +-- Clone/fetch repo with GITHUB_TOKEN
        |       |       +-- Checkout PR branch
        |       |       +-- Generate diff (origin/base...branch, max 50KB)
        |       |       +-- Run: claude -p "Review this PR..." --output-format text
        |       |       +-- Return review text + duration (timeout: 300s)
        |       |
        |       +-- 2. If Claude Code fails --> Fallback to Open WebUI
        |       |       |
        |       |       +-- Fetch PR files via GitHub API
        |       |       +-- Enrich with repo context + Loki error logs
        |       |       +-- Send to Open WebUI for AI analysis
        |       |
        |       +-- 3. Post review as GitHub PR comment
        |       +-- 4. Send Discord notification with review summary
        |
        +-- "push"
        |       +-- Discord notification (branch, commits, author)
        |       +-- AI analysis of commits
        |       +-- Forward to n8n github-push workflow
        |
        +-- "issues" (opened)
        |       +-- AI analysis via Open WebUI
        |       +-- Post AI comment on issue
        |
        +-- "pull_request" (merged)
        |       +-- Discord notification
        |       +-- Generate deployment notes via AI
        |       +-- Post deployment notes as PR comment
        |
        +-- "ping" --> Respond "Pong!"
```

---

## How Discord Slash Commands Work (/aiui)

```
User types /aiui ask "what is MCP?" in Discord
        |
   Discord sends POST /webhook/discord (JSON, Ed25519 signed)
        |
   Caddy --> webhook-handler:8086
        |
   Verify Ed25519 signature (DISCORD_PUBLIC_KEY)
        |
   Check interaction type:
        |
        +-- PING (type 1)
        |       +-- Return PONG (type 1) — Discord requires this for endpoint validation
        |
        +-- APPLICATION_COMMAND (type 2)
                |
                +-- Return DEFERRED response (type 5) immediately (< 3 seconds!)
                |
                +-- Background task starts:
                |       |
                |       +-- Parse options --> subcommand + arguments
                |       +-- CommandRouter dispatches to correct handler
                |       |       |
                |       |       +-- Routes to handler based on subcommand
                |       |       +-- (see Command Router section below)
                |       |
                |       +-- Result edits the deferred "thinking..." message
                |
                +-- Discord shows "Bot is thinking..." until result arrives
```

**Why deferred?** Discord requires a response within 3 seconds. AI processing takes 5-120s, so we ACK immediately and edit the message later.

---

## How Slack Slash Commands Work (/aiui)

```
User types /aiui status in Slack
        |
   Slack sends POST /webhook/slack/commands (form-encoded, NOT JSON!)
        |
   Caddy --> webhook-handler:8086
        |
   Verify HMAC-SHA256 signature (SLACK_SIGNING_SECRET + timestamp)
        |
   Return ACK immediately: "Processing..."
        |
   Background task starts:
        |
        +-- Parse form data --> command, text, response_url, user_id, channel_id
        +-- CommandRouter dispatches to correct handler
        +-- Result posted back via Slack's response_url (pre-authenticated, no token needed)
```

---

## Command Router — All /aiui Subcommands

Both Slack and Discord use the same CommandRouter. Platform-agnostic.

| Command | Example | What Happens | Calls |
|---------|---------|-------------|-------|
| **ask** | `/aiui ask what is MCP?` | Send question to AI, return answer | Open WebUI |
| **status** | `/aiui status` | Health check all services | Health endpoints |
| **workflow** | `/aiui workflow pr-review` | Find n8n workflow by name, trigger it | n8n API |
| **workflows** | `/aiui workflows` | List all active n8n workflows | n8n API |
| **pr-review** | `/aiui pr-review 42` | Fetch PR #42, run AI review | GitHub + Open WebUI |
| **report** | `/aiui report` | End-of-day summary: commits + executions + health | GitHub + n8n + Health |
| **diagnose** | `/aiui diagnose webhook-handler` | Query logs for errors, AI diagnosis | Loki + Open WebUI |
| **analyze** | `/aiui analyze owner/repo` | Fetch repo structure, AI analysis | GitHub + Open WebUI |
| **email** | `/aiui email` | Trigger Gmail summary workflow | n8n |
| **sheets** | `/aiui sheets daily` | Generate report to Google Sheets | n8n |
| **mcp** | `/aiui mcp github list_repos {}` | Execute MCP tool directly | MCP Proxy |
| **help** | `/aiui help` | Show all available commands | — |

**Default behavior:** Unknown text treated as `ask`. Empty input treated as `status`.

---

## How Discord Notifications Work

```
Event happens (PR opened, push, alert, etc.)
        |
   webhook-handler builds message
        |
   POST to Discord API --> channels/{DISCORD_ALERT_CHANNEL_ID}/messages
        |
   Auth: Bot {DISCORD_BOT_TOKEN}
   Body: message text (max 2000 chars, auto-truncated)
        |
   Discord shows message in the alert channel
```

**Events that trigger Discord notifications:**

| Event | What Shows Up |
|-------|--------------|
| PR opened | "New PR #N: title by author -> base_branch" |
| PR merged | "PR #N merged: title by author into base_branch" |
| PR closed | "PR #N closed: title by author" |
| PR reviewed (Claude Code) | "Full repo checkout analyzed in Xs by Claude Code CLI" + findings preview |
| PR reviewed (Open WebUI) | "Reviewed by Open WebUI (diff-only)" |
| Push | "Push to branch: N commits by pusher" |
| Grafana alert | Alert details + AI diagnosis with source code context |

---

## How n8n Workflows Work

```
                     +-----------------------+
                     |    n8n Engine :5678    |
                     |   (workflow runner)    |
                     +-----------------------+
                          |            |
               Webhook triggers   API triggers
                    |                  |
    External:       |     Internal:    |
    /n8n/webhook/*  |     POST /api/v1/workflows/{id}/execute
    (via Caddy)     |     (authenticated with API key)
                    |                  |
             +------+------+   +------+------+
             | Workflow    |   | Workflow    |
             | Nodes       |   | Nodes       |
             | (HTTP, AI,  |   | (Gmail,     |
             |  GitHub...) |   |  Sheets...) |
             +-------------+   +-------------+
```

**Active Workflows:**

| Workflow | Trigger | What It Does |
|----------|---------|-------------|
| **PR Review Automation** | Webhook: `pr-review` | Fetch PR diff, AI review, post GitHub comment |
| **Gmail Inbox Summary** | Webhook: `gmail-inbox-summary` | Read Gmail, summarize emails |
| **Sheets Report** | Webhook: `sheets-report` | Gather data, write to Google Sheets |
| **GitHub Push Processor** | Forwarded from webhook-handler | Process push events |

**How /aiui triggers n8n workflows:**

```
User types /aiui workflow pr-review
        |
   CommandRouter:
     1. Lists all workflows via n8n API
     2. Finds matching workflow by name
     3. Extracts webhook path from workflow's webhook node
     4. Triggers: POST {n8n_url}/webhook/{path}
        |
   n8n executes the workflow
        |
   Result returned to user in Discord/Slack
```

**Critical gotcha:** Webhook nodes MUST have a `webhookId` field, otherwise production listeners silently return 404 even though the workflow shows as "active" in the n8n UI.

---

## How the PR Review Pipeline Works (End to End)

```
Developer pushes code --> Creates/updates PR on GitHub
        |
   GitHub fires webhook POST /webhook/github
        |
   webhook-handler receives it
        |
   Is it a PR opened/synchronize event?
        |
   YES --> Start PR review pipeline:
        |
        +--[1] Try Claude Code (pr-reviewer container)
        |       |
        |       Sends request to pr-reviewer:3000
        |       |
        |       pr-reviewer container:
        |         +-- Validate inputs (safe characters only)
        |         +-- Clone or fetch repo (authenticated git)
        |         +-- Checkout PR branch
        |         +-- Generate diff (max 50KB)
        |         +-- Run Claude Code CLI against full codebase
        |         +-- Claude reads diff + source files + CLAUDE.md guidelines
        |         +-- Returns structured review (timeout: 300s)
        |       |
        |       Success? --> review text + duration
        |       Fail/timeout? --> fallback below
        |
        +--[2] Fallback: Open WebUI
        |       |
        |       +-- Fetch PR files via GitHub API (diff summary)
        |       +-- Enrich with repo context + recent error logs
        |       +-- Send to Open WebUI AI for analysis
        |       +-- Returns review text
        |
        +--[3] Post review as GitHub PR comment
        |       Tagged: "Reviewed by Claude Code" or "Reviewed by Open WebUI"
        |
        +--[4] Send Discord notification
                |
                Claude Code: "Full repo checkout analyzed in 125.2s by Claude Code CLI"
                Open WebUI:  "Reviewed by Open WebUI (diff-only)"
                + findings preview (Summary, Bugs, Security)
                + link to PR
```

---

## How Grafana Alerts Work

```
All containers output logs (stdout/stderr)
        |
   Promtail ships logs to Loki (auto-discovers all containers)
        |
   Grafana queries Loki with alert rules
        |
   Alert fires (HTTP 500 spike, high error rate, etc.)
        |
   POST /webhook/grafana-alerts --> webhook-handler
        |
        +-- Format alert for Discord --> Post to alert channel
        |
        +-- If alert is FIRING:
        |       +-- Query Loki for error logs (last 5 min)
        |       +-- Extract file references from stack traces
        |       +-- Fetch source code via MCP GitHub
        |       +-- AI diagnosis with full code context
        |       +-- Post diagnosis to Discord
        |
        +-- If alert is RESOLVED:
                +-- Post resolution notification to Discord
```

---

## How MCP (Model Context Protocol) Works

```
User asks AI in Open WebUI: "Create a GitHub issue for this bug"
        |
   Open WebUI sees available tools (from MCP Proxy)
        |
   AI decides to call: github/create_issue
        |
   Open WebUI --> API Gateway (adds user identity headers)
        |
   API Gateway --> MCP Proxy :8000
        |
   MCP Proxy checks:
     - Is user's group allowed to access "github" server?
     - Is this tool allowed for this user?
        |
   YES --> Forward to mcp-github:8000
        |
   mcp-github executes the tool
        |
   Result flows back: mcp-github --> MCP Proxy --> Gateway --> Open WebUI --> AI
        |
   AI formats result and shows to user
```

**Multi-Tenant Access Control:**
```
Group "Tenant-Google":     github, linear, notion, filesystem, atlassian
Group "Tenant-Microsoft":  github, filesystem, atlassian, gitlab
Group "MCP-Admin":         ALL servers (full access)
```

---

## Observability Stack

```
All Docker containers (stdout/stderr)
        |
   Promtail (auto-discovers containers via Docker socket)
        |
   Applies labels: container_name, service, project, log_level
        |
   Pushes to Loki :3100 (stored 7 days)
        |
   Queryable via:
        +-- Grafana UI at /grafana/explore (visual log explorer)
        +-- /aiui diagnose command (AI-powered error analysis)
        +-- Grafana Alert Rules (auto-fires on error patterns)
```

---

## Scheduler & Cron Jobs

```
APScheduler runs inside webhook-handler
        |
   Default jobs:
     +-- daily_health_report (8 AM) --> Posts service status to Slack
     +-- hourly_n8n_workflow_check --> Verifies n8n is responsive
        |
   User-created jobs via API:
     POST /scheduler/jobs with cron expression + workflow to trigger
        |
   Guardrails:
     - Min interval: 1 minute
     - Max jobs per user: 10
     - Default expiry: 24 hours (unless permanent)
```

---

## Authentication Flow

```
User visits ai-ui.coolestdomain.win
        |
   Open WebUI login page (or Microsoft OAuth)
        |
   Open WebUI sets JWT cookie
        |
   All subsequent requests include cookie
        |
   Caddy --> API Gateway
        |
   API Gateway:
     1. Extract JWT from cookie or Authorization header
     2. Decode and validate signature
     3. Lookup user in Postgres (email, groups, admin status)
     4. Inject headers: X-User-Email, X-User-Groups, X-User-Admin
     5. Forward to backend service
        |
   Backend trusts gateway headers (no double-auth)
```

---

## Network Architecture

```
                    FRONTEND network
                    (Caddy only)
                         |
                      [ Caddy ]
                         |
                    BACKEND network
                    (all services)
                         |
    +----+----+----+----+----+----+----+----+
    |    |    |    |    |    |    |    |    |
  API  Open  Web  MCP  n8n  PR   Loki Gra-
  GW   WebUI hook Proxy     Rev       fana
              Hndl
                |
           +----+----+
           |    |    |
         Postgres Redis
                          |
                    MCP Tool Servers
                    (github, excel,
                     clickup, notion,
                     filesystem, etc.)
```

---

## Memory & Resource Limits

| Service | Memory Limit | Notes |
|---------|-------------|-------|
| pr-reviewer | 512 MB | Mutex lock: 1 review at a time |
| mcp-n8n | 512 MB | n8n workflow management tools |
| mcp-scheduler | 256 MB | Cron job management |
| Server total | 3.8 GB | No swap configured |

**Stopped to save memory:** mcp-clickup, mcp-trello, mcp-sonarqube, mcp-scheduler (start when needed)

---

## Quick Reference: What Calls What

```
GitHub webhook --> webhook-handler --> pr-reviewer (Claude Code)
                                  --> Open WebUI (fallback)
                                  --> Discord (notification)
                                  --> GitHub API (post comment)

Discord /aiui  --> webhook-handler --> CommandRouter --> Open WebUI (ask)
                                                    --> n8n (workflow, email, sheets)
                                                    --> GitHub (pr-review, analyze)
                                                    --> Loki (diagnose)
                                                    --> MCP Proxy (mcp)
                                                    --> Health endpoints (status)

Slack /aiui    --> webhook-handler --> CommandRouter --> (same as Discord above)

Grafana alert  --> webhook-handler --> Discord (alert message)
                                  --> Loki (error context)
                                  --> MCP GitHub (source code)
                                  --> Open WebUI (AI diagnosis)
                                  --> Discord (diagnosis)

Browser        --> Caddy --> API Gateway --> Open WebUI (chat)
                                        --> MCP Proxy --> MCP servers (tools)
```
