# Local Dev Setup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add webhook-handler to `docker-compose.yml` and update `.env.example` so developers can run the full platform locally after `git clone`.

**Architecture:** Add webhook-handler service to existing local compose file, connecting to Open WebUI and MCP Proxy via Docker network. n8n stays remote (hosted). Update `.env.example` with all required vars.

**Tech Stack:** Docker Compose, Python/FastAPI (webhook-handler), environment variables

---

### Task 1: Add webhook-handler service to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml:263-278` (before volumes section)

**Step 1: Add the webhook-handler service block**

Insert before the `volumes:` section (line 279) in `docker-compose.yml`:

```yaml
  # ==========================================================================
  # Webhook Handler - Discord/Slack Bot + Event Processing
  # ==========================================================================
  webhook-handler:
    build: ./webhook-handler
    container_name: webhook-handler
    ports:
      - "8086:8086"
    environment:
      # Service
      - PORT=8086
      - DEBUG=${DEBUG:-false}
      # Open WebUI (Docker internal)
      - OPENWEBUI_URL=http://open-webui:8080
      - OPENWEBUI_API_KEY=${OPENWEBUI_API_KEY}
      - AI_MODEL=${AI_MODEL:-gpt-4-turbo}
      # MCP Proxy (Docker internal)
      - MCP_PROXY_URL=http://mcp-proxy:8000
      - MCP_API_KEY=${MCP_API_KEY:-test-key}
      # GitHub
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}
      # n8n (remote hosted instance)
      - N8N_URL=${N8N_API_URL:-http://n8n:5678}
      - N8N_WEBHOOK_URL=${N8N_WEBHOOK_URL:-http://n8n:5678}
      - N8N_API_KEY=${N8N_API_KEY}
      # Discord Bot
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - DISCORD_APPLICATION_ID=${DISCORD_APPLICATION_ID}
      - DISCORD_PUBLIC_KEY=${DISCORD_PUBLIC_KEY}
      - DISCORD_ALERT_CHANNEL_ID=${DISCORD_ALERT_CHANNEL_ID}
      # ElevenLabs Voice
      - ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY}
      - ELEVENLABS_AGENT_ID=${ELEVENLABS_AGENT_ID}
      - VOICE_WEBHOOK_SECRET=${VOICE_WEBHOOK_SECRET}
      # Loki (not available locally — handler degrades gracefully)
      - LOKI_URL=${LOKI_URL:-http://loki:3100}
      # Reporting
      - REPORT_GITHUB_REPO=${REPORT_GITHUB_REPO:-TheLukasHenry/proxy-server}
    depends_on:
      open-webui:
        condition: service_started
      mcp-proxy:
        condition: service_started
    restart: unless-stopped
```

**Step 2: Verify compose file is valid**

Run: `docker compose config --quiet`
Expected: No errors (exit code 0)

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add webhook-handler to local docker-compose"
```

---

### Task 2: Update .env.example with webhook-handler vars

**Files:**
- Modify: `.env.example:148-181` (Webhook Handler + n8n sections)

**Step 1: Replace the Webhook Handler and n8n sections with complete vars**

Replace everything from line 148 (`# Webhook Handler Configuration`) to end of file with:

```env
# =============================================================================
# Webhook Handler Configuration
# =============================================================================

# GitHub webhook secret (configure same value in GitHub webhook settings)
GITHUB_WEBHOOK_SECRET=your-webhook-secret-here

# Open WebUI API key (get from Open WebUI Settings > Account > API Keys)
OPENWEBUI_API_KEY=your-openwebui-api-key

# AI Model to use for analysis
AI_MODEL=gpt-4-turbo

# =============================================================================
# Discord Bot Integration
# =============================================================================
# Get these from https://discord.com/developers/applications

# Bot token (Bot > Token > Reset Token)
DISCORD_BOT_TOKEN=

# Application ID (General Information > Application ID)
DISCORD_APPLICATION_ID=

# Public Key (General Information > Public Key)
DISCORD_PUBLIC_KEY=

# Channel ID for alerts (right-click channel > Copy Channel ID)
DISCORD_ALERT_CHANNEL_ID=

# =============================================================================
# ElevenLabs Voice Integration (Optional)
# =============================================================================
# Get from https://elevenlabs.io/app/settings

ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
VOICE_WEBHOOK_SECRET=aiui-voice-2026

# =============================================================================
# n8n Workflow Engine (Remote Hosted)
# =============================================================================

# n8n API URL (hosted instance — not local)
N8N_API_URL=https://n8n.srv1041674.hstgr.cloud

# External webhook URL for n8n
N8N_WEBHOOK_URL=https://n8n.srv1041674.hstgr.cloud

# n8n API key (generate from n8n Settings > API > Create API Key)
N8N_API_KEY=

# =============================================================================
# Reporting
# =============================================================================

# Default GitHub repo for analysis commands (owner/repo format)
REPORT_GITHUB_REPO=TheLukasHenry/proxy-server

# Slack channel for daily reports (optional)
REPORT_SLACK_CHANNEL=

# =============================================================================
# Logging & Observability (Optional — production only)
# =============================================================================

# Loki log aggregation (not available in local dev)
LOKI_URL=http://loki:3100

# Grafana admin password
GRAFANA_ADMIN_PASSWORD=

# LangFuse LLM observability
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add Discord, ElevenLabs, n8n vars to .env.example"
```

---

### Task 3: Test local docker compose up

**Step 1: Validate compose file**

Run: `docker compose config --quiet`
Expected: Exit code 0, no errors

**Step 2: Build webhook-handler image**

Run: `docker compose build webhook-handler`
Expected: Build succeeds, image created

**Step 3: Start the stack**

Run: `docker compose up -d`
Expected: All containers start (redis, postgres, ollama, open-webui, mcp-proxy, mcp servers, webhook-handler, db-init)

**Step 4: Check webhook-handler logs**

Run: `docker compose logs webhook-handler --tail 20`
Expected: Should see:
- "Initializing webhook handler..."
- "Discord slash commands enabled" (if Discord vars set)
- "Voice bot starting as background task" (if ElevenLabs vars set)
- "Webhook handler ready on port 8086"

**Step 5: Test health endpoint**

Run: `curl http://localhost:8086/health`
Expected: `{"status":"healthy","service":"webhook-handler","version":"2.0.0"}`

**Step 6: Test Open WebUI is accessible**

Run: `curl -s http://localhost:3000 | head -5`
Expected: HTML response (Open WebUI frontend)
