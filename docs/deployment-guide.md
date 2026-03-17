# IO Platform Deployment Guide

## Server Information

- **Provider:** Hetzner VPS
- **IP Address:** 46.224.193.25
- **Domain:** ai-ui.coolestdomain.win (behind Cloudflare)
- **RAM:** 3.8GB — avoid building multiple containers simultaneously (OOM risk)
- **Deploy Directory:** /root/proxy-server/
- **SSH Access:** root@46.224.193.25

## Deployment Process

There is no git installed on the production server. All deployments happen via SCP followed by Docker Compose rebuild.

### Step 1: Copy Files to Server

Copy individual files to the server using SCP:

```bash
scp file root@46.224.193.25:/root/proxy-server/path/to/file
```

**Important:** `scp -r` may silently skip files. For critical deployments, copy files individually rather than using recursive mode:

```bash
# Correct — copy individual files
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py

# Risky — may silently skip files
scp -r webhook-handler/ root@46.224.193.25:/root/proxy-server/webhook-handler/
```

### Step 2: Rebuild and Restart the Service

After copying files, SSH into the server and rebuild the specific service:

```bash
ssh root@46.224.193.25
cd /root/proxy-server
docker compose -f docker-compose.unified.yml up -d --build <service>
```

Replace `<service>` with the service name from docker-compose.unified.yml (e.g., `webhook-handler`, `api-gateway`, `mcp-proxy`).

### Step 3: Use --no-cache if Layers Are Stale

If Docker caches stale layers and your changes don't appear, force a clean rebuild:

```bash
docker compose -f docker-compose.unified.yml build --no-cache <service>
docker compose -f docker-compose.unified.yml up -d <service>
```

### Memory Considerations

With only 3.8GB RAM, be careful:

- Build one service at a time — never run multiple `--build` commands in parallel.
- If a build fails with OOM, stop non-essential containers first, build, then restart everything.
- Monitor memory with `free -h` or `docker stats` before building.

## Caddy Routes Summary

All traffic flows through Caddy on port 80. The routing determines which backend handles each request.

| Route | Destination | Notes |
|---|---|---|
| `/health` | Returns "OK" directly | Caddy responds, no backend |
| `/caddy/health` | Returns "Caddy OK" directly | Caddy responds, no backend |
| `/gateway/*` | api-gateway:8080 | Direct to gateway |
| `/webhook/*` | webhook-handler:8086 | Discord/GitHub webhooks |
| `/n8n/*` | n8n:5678 | Strip `/n8n` prefix, workflow engine |
| `/grafana/*` | grafana:3000 | Log dashboard, bypasses gateway |
| `/mcp/*` | api-gateway:8080 | MCP proxy (authenticated) |
| `/servers*` | api-gateway:8080 | Rewritten to /mcp/servers |
| `/meta/*` | api-gateway:8080 | Rewritten to /mcp/meta |
| `/openapi.json` | api-gateway:8080 | Rewritten to /mcp/openapi.json |
| `/mcp-admin`, `/mcp-admin/*` | api-gateway:8080 | Admin portal |
| `/admin/*` | api-gateway:8080 | Admin routes |
| `/portal*` | api-gateway:8080 | Redirects to /mcp-admin |
| `/_app/*` | open-webui:8080 | Static assets, bypasses gateway |
| `/static/*` | open-webui:8080 | Static assets, bypasses gateway |
| `/favicon*` | open-webui:8080 | Favicon, bypasses gateway |
| `/manifest.json` | open-webui:8080 | PWA manifest, bypasses gateway |
| `/ws/*` | open-webui:8080 | WebSocket, bypasses gateway |
| `/*` (default) | api-gateway:8080 | Open WebUI via gateway for auth |

**Why static assets bypass the gateway:** Open WebUI loads 60+ JS/CSS chunks on page load. If these go through the API Gateway's rate limiter, they get 429 errors and the page appears blank or broken.

**Cloudflare note:** All requests may appear from the same IP because Cloudflare masks client IPs. Use the `CF-Connecting-IP` header for real client IPs in rate limiting logic.

## Traffic Flow

```
Browser → Cloudflare → Caddy (port 80) → API Gateway (8080) → Backend Services
```

The API Gateway handles:
- JWT validation
- Rate limiting
- User header injection
- Request forwarding to backend services (Open WebUI, MCP Proxy, Admin Portal)

## Key Environment Variables

All environment variables are defined in `/root/proxy-server/.env` on the server. Never commit this file to git.

### Authentication
- `WEBUI_SECRET_KEY` — Open WebUI JWT signing key
- `DISCORD_BOT_TOKEN` — Discord bot authentication
- `DISCORD_PUBLIC_KEY` — Discord interaction verification
- `DISCORD_APPLICATION_ID` — Discord application identifier
- `DISCORD_ALERT_CHANNEL_ID` — Channel for alert notifications
- `GITHUB_TOKEN` — GitHub API access
- `GITHUB_WEBHOOK_SECRET` — GitHub webhook signature verification

### Database
- `POSTGRES_PASSWORD` — PostgreSQL password
- `DATABASE_URL` — Full database connection string
- `REDIS_URL` — Redis connection string

### AI / LLM
- `OPENAI_API_KEY` — OpenAI API access
- `AI_MODEL` — Default model selection
- `OPENWEBUI_API_KEY` — Open WebUI API key

### Voice
- `ELEVENLABS_API_KEY` — ElevenLabs text-to-speech
- `ELEVENLABS_AGENT_ID` — ElevenLabs agent identifier
- `VOICE_WEBHOOK_SECRET` — Voice webhook authentication

### Monitoring
- `LOKI_URL` — Loki log aggregation endpoint
- `GRAFANA_ADMIN_PASSWORD` — Grafana dashboard admin password
- `LANGFUSE_SECRET_KEY` — Langfuse observability

### MCP (Model Context Protocol)
- `MCP_API_KEY` — MCP proxy authentication
- `LINEAR_API_KEY` — Linear project management
- `NOTION_API_KEY` — Notion integration
- `ATLASSIAN_API_KEY` — Atlassian/Jira integration
- `CLICKUP_API_TOKEN` — ClickUp integration

### n8n (Workflow Engine)
- `N8N_API_KEY` — n8n API access
- `N8N_URL` — n8n base URL
- `N8N_WEBHOOK_URL` — n8n webhook endpoint

## Common Operations

### Viewing Logs

```bash
# Follow logs for a specific service
docker compose -f docker-compose.unified.yml logs -f <service>

# Last 100 lines
docker compose -f docker-compose.unified.yml logs --tail=100 <service>
```

### Restarting a Service (Without Rebuild)

```bash
docker compose -f docker-compose.unified.yml restart <service>
```

### Checking Service Health

```bash
# All services
docker compose -f docker-compose.unified.yml ps

# Memory usage
docker stats --no-stream
```

### Full Stack Restart

```bash
cd /root/proxy-server
docker compose -f docker-compose.unified.yml down
docker compose -f docker-compose.unified.yml up -d
```
