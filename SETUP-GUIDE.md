# IO Platform - Setup Guide

> For the developer receiving this zip. Read this first before touching anything.

---

## What Is This

A backend automation platform that connects:
- **Open WebUI** (AI chat interface with pipe functions)
- **MCP Proxy** (multi-tenant tool gateway — GitHub, Linear, Notion, Slack, etc.)
- **n8n** (workflow automation)
- **Webhook Handler** (FastAPI service that glues everything together)

The core flow: **External event (GitHub webhook, cron job, API call) -> Webhook Handler -> Open WebUI AI analysis + MCP tool execution + n8n workflow triggers -> Structured response back**

---

## Architecture

```
                                    +------------------+
                                    |   GitHub / Slack  |
                                    |   (webhooks)      |
                                    +--------+---------+
                                             |
                                             v
+----------+     +-----------+     +---------+---------+     +-------------+
|  Caddy   +---->+   API     +---->+  Webhook Handler  +---->+  Open WebUI |
| (port 80)|     | Gateway   |     |  (port 8086)      |     |  (port 3000)|
+----------+     +-----------+     +----+----+----+----+     +-------------+
                                        |    |    |
                            +-----------+    |    +----------+
                            v                v               v
                     +------+------+  +------+------+  +-----+-----+
                     |  MCP Proxy  |  |     n8n     |  |  Scheduler|
                     |  (internal) |  | (port 5678) |  | (APSched) |
                     +------+------+  +-------------+  +-----------+
                            |
              +-------------+-------------+
              v             v             v
        +---------+   +---------+   +---------+
        | GitHub  |   | ClickUp |   | Linear  |  ... more MCP servers
        | Server  |   | Server  |   | Server  |
        +---------+   +---------+   +---------+
```

**16 Docker containers** in the unified compose file.

---

## Prerequisites

- **Docker Desktop** (with Docker Compose v2)
- **Git**
- **PowerShell** (for running test/demo scripts on Windows)
- An **OpenAI API key** (or compatible LLM provider)
- A **GitHub Personal Access Token** (for MCP GitHub tools)

---

## Step 1: Environment Setup

```bash
# Copy the example env file
cp .env.example .env
```

Edit `.env` and fill in these **required** values:

| Variable | Where to get it | What it does |
|----------|----------------|--------------|
| `WEBUI_SECRET_KEY` | Generate any random string | JWT signing for Open WebUI |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys | LLM provider for AI analysis |
| `OPENAI_API_BASE_URL` | `https://api.openai.com/v1` | OpenAI base URL |
| `GITHUB_TOKEN` | GitHub Settings > Developer Settings > PAT | MCP GitHub tools + webhook comments |
| `POSTGRES_PASSWORD` | Choose any password | Database password |
| `MCP_API_KEY` | Choose any string (e.g. `mcp-secret-key`) | Internal auth between proxy and MCP servers |

**Optional but recommended:**

| Variable | Purpose |
|----------|---------|
| `OPENWEBUI_API_KEY` | Get from Open WebUI after first login (Settings > Account > API Keys) |
| `N8N_API_KEY` | Get from n8n after first login (Settings > API) |
| `GITHUB_WEBHOOK_SECRET` | For verifying GitHub webhook signatures |
| `AI_MODEL` | Default model for AI analysis (e.g. `gpt-4o-mini`, `gpt-5`) |
| `LINEAR_API_KEY` | For Linear MCP tools |
| `NOTION_API_KEY` | For Notion MCP tools |
| `SLACK_BOT_TOKEN` | For Slack integration |

---

## Step 2: Start Everything

```bash
docker compose -f docker-compose.unified.yml up -d --build
```

This builds and starts all 16 services. First run takes 5-10 minutes (downloading images, building containers).

**Watch the logs:**
```bash
docker compose -f docker-compose.unified.yml logs -f
```

**Check all containers are running:**
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

You should see: `caddy`, `api-gateway`, `webhook-handler`, `n8n`, `mcp-proxy`, `open-webui`, `admin-portal`, `postgres`, `redis`, `mcp-github`, `mcp-filesystem`, `mcp-trello`, `mcp-sonarqube`, `mcp-excel`, `mcp-dashboard`

---

## Step 3: First Login to Open WebUI

1. Go to **http://localhost:3000**
2. Create an admin account (first user becomes admin automatically)
3. Go to **Settings > Account > API Keys** and generate one
4. Copy that key into `.env` as `OPENWEBUI_API_KEY`
5. Restart webhook-handler: `docker compose -f docker-compose.unified.yml restart webhook-handler`

---

## Step 4: Install the Webhook Automation Pipe

This is the pipe function that lets Open WebUI process webhook payloads with AI + MCP tools.

```bash
docker compose -f docker-compose.unified.yml exec webhook-handler python /app/scripts/install_webhook_pipe.py
```

After this, **"Webhook Automation"** appears as a model in Open WebUI's model selector.

---

## Step 5: Set Up n8n

1. Go to **http://localhost:5678**
2. Create an account
3. Go to **Settings > API** and create an API key
4. Copy that key into `.env` as `N8N_API_KEY`
5. Restart webhook-handler: `docker compose -f docker-compose.unified.yml restart webhook-handler`

**Import the GitHub Push Processor workflow:**
```bash
powershell -ExecutionPolicy Bypass -File scripts/deploy-n8n-github-workflow.ps1
```

Or manually import `n8n-workflows/github-push-processor.json` via n8n UI (Settings > Import).

---

## Step 6: Verify Everything Works

**Quick health checks:**
```
GET http://localhost:8086/health              -> webhook-handler
GET http://localhost:3000/api/config          -> Open WebUI
GET http://localhost:5678/healthz             -> n8n
GET http://localhost:8086/scheduler/jobs      -> 2 scheduled jobs
GET http://localhost:8086/scheduler/health-report  -> all services status
```

**Run the full demo script:**
```bash
powershell -ExecutionPolicy Bypass -File scripts/run-full-demo.ps1
```

**Run the requirements verification:**
```bash
powershell -ExecutionPolicy Bypass -File scripts/verify-lukas-requirements.ps1
```

---

## Key Services & Ports

| Service | Port | URL | Purpose |
|---------|------|-----|---------|
| Open WebUI | 3000 | http://localhost:3000 | AI chat interface |
| n8n | 5678 | http://localhost:5678 | Workflow automation |
| Webhook Handler | 8086 | http://localhost:8086 | Event processing + scheduler |
| API Gateway | 8085 | http://localhost:8085 | Auth + rate limiting |
| Caddy | 80/443 | http://localhost | Reverse proxy (production) |
| MCP Proxy | internal | (not exposed) | Tool gateway (Docker network only) |
| PostgreSQL | internal | (not exposed) | Database |
| Redis | internal | (not exposed) | Sessions + cache |

---

## Webhook Handler API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/webhook/github` | GitHub webhook receiver (signature verified) |
| `POST` | `/webhook/mcp/{server}/{tool}` | Execute MCP tool directly |
| `POST` | `/webhook/n8n/{path}` | Forward payload to n8n workflow |
| `POST` | `/webhook/slack` | Slack Events API |
| `POST` | `/webhook/automation` | Full AI + MCP + n8n automation chain |
| `POST` | `/webhook/generic` | Generic webhook with AI analysis |
| `GET` | `/scheduler/jobs` | List scheduled jobs |
| `POST` | `/scheduler/jobs/{id}/trigger` | Manually trigger a job |
| `GET` | `/scheduler/health-report` | On-demand health report |
| `GET` | `/scheduler/n8n-check` | Check n8n workflow status |

Full Swagger docs: **http://localhost:8086/docs**

---

## Multi-Tenancy

The MCP Proxy filters tools by user group. Config is in `mcp-proxy/config/mcp-servers.json`.

**Current tenants:**

| Tenant | Sees servers |
|--------|-------------|
| `MCP-Admin` | All servers (full access) |
| `Test-Tenant` | github, filesystem only |
| `Tenant-Google` | github, linear, notion, filesystem, slack |
| `Tenant-Microsoft` | github, notion, filesystem |
| `Tenant-AcmeCorp` | github, clickup, filesystem |

To test isolation, use the `X-User-Groups` header when calling the MCP proxy:
```bash
# Admin sees everything
curl http://localhost:8086/webhook/mcp/github/github_get_me -X POST -H "Content-Type: application/json" -d "{}"

# Inside Docker (MCP proxy is internal only):
docker exec mcp-proxy python -c "
import httpx
r = httpx.get('http://localhost:8000/tools', headers={'X-User-Email': 'test@t.com', 'X-User-Groups': 'Test-Tenant'})
print(len(r.json().get('tools', r.json())), 'tools')
"
```

---

## Scheduled Jobs

Two built-in jobs (configured in `webhook-handler/scheduler.py`):

| Job ID | Schedule | What it does |
|--------|----------|-------------|
| `daily_health_report` | Every day at noon (12:00) | Checks health of all 4 services |
| `hourly_n8n_check` | Every hour at :00 | Lists active/inactive n8n workflows |

Trigger manually:
```bash
curl -X POST http://localhost:8086/scheduler/jobs/daily_health_report/trigger
```

---

## The Automation Pipe (How It Works)

When you send a message to the **Webhook Automation** model in Open WebUI (or call `/webhook/automation`), it goes through 4 phases:

1. **Parse** - Extracts source, event type, and payload from the message
2. **Plan** - LLM decides which MCP tools and n8n workflows to use
3. **Execute** - Calls the chosen MCP tools via proxy + triggers n8n workflows
4. **Summarize** - LLM produces a structured summary of results

Source code: `open-webui-functions/webhook_pipe.py`

---

## Project Structure

```
IO/
+-- docker-compose.unified.yml    # Main compose file (use this one)
+-- .env                          # Environment variables (create from .env.example)
+-- Caddyfile                     # Reverse proxy config
+-- webhook-handler/              # FastAPI webhook service
|   +-- main.py                   # App entry point + all routes
|   +-- config.py                 # Settings from env vars
|   +-- scheduler.py              # APScheduler cron jobs
|   +-- handlers/                 # Event handlers (github, mcp, slack, automation)
|   +-- clients/                  # API clients (openwebui, github, n8n, mcp_proxy)
+-- mcp-proxy/                    # Multi-tenant MCP tool gateway
|   +-- config/mcp-servers.json   # Server + tenant config
+-- open-webui-functions/         # Pipe functions for Open WebUI
|   +-- webhook_pipe.py           # The automation pipe (4-phase processing)
+-- n8n-workflows/                # Exportable n8n workflow definitions
+-- mcp-servers/                  # Custom MCP server builds (github, excel, dashboard)
+-- api-gateway/                  # JWT validation + rate limiting
+-- admin-portal/                 # User/group management UI
+-- scripts/                      # Setup + demo scripts
|   +-- install_webhook_pipe.py   # Installs pipe function into Open WebUI DB
|   +-- run-full-demo.ps1         # Full cross-service demo
|   +-- verify-lukas-requirements.ps1  # Requirement verification
|   +-- deploy-n8n-github-workflow.ps1 # Deploy n8n workflow
+-- archive/                      # Old/deprecated files (ignore)
+-- docs/                         # Architecture documentation
```

---

## Troubleshooting

**Container won't start?**
```bash
docker compose -f docker-compose.unified.yml logs <service-name>
```

**Webhook Automation model not showing in Open WebUI?**
Run the pipe installer again:
```bash
docker compose -f docker-compose.unified.yml exec webhook-handler python /app/scripts/install_webhook_pipe.py
```

**MCP tools returning errors?**
Check if the MCP server containers are running and the API keys are set in `.env`.

**n8n workflows not triggering?**
Make sure the workflow is **Published** (not just saved) in n8n, and `N8N_API_KEY` is set.

**Scheduler jobs not running?**
Check webhook-handler logs:
```bash
docker logs webhook-handler --tail 50
```

**Need to rebuild after code changes?**
```bash
docker compose -f docker-compose.unified.yml up -d --build <service-name>
```

---

## Quick Test Commands

```bash
# Health check
curl http://localhost:8086/health

# List scheduled jobs
curl http://localhost:8086/scheduler/jobs

# Run health report
curl http://localhost:8086/scheduler/health-report

# Test GitHub MCP tool
curl -X POST http://localhost:8086/webhook/mcp/github/github_get_me -H "Content-Type: application/json" -d "{}"

# Test automation chain (needs pipe installed + LLM access)
curl -X POST "http://localhost:8086/webhook/automation?source=test&instructions=List+available+MCP+tools" -H "Content-Type: application/json" -d '{"test": true}'
```
