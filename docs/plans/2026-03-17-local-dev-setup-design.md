# Local Dev Setup — Design Doc

**Date:** 2026-03-17
**Goal:** Fix `docker-compose.yml` so after `git clone` + `.env` setup + `docker compose up`, the full platform works locally including Discord bot and KB-powered answers.

## What Changes

### 1. Add webhook-handler to `docker-compose.yml`
- Build from `./webhook-handler`
- Port: `8086:8086`
- Connects to `open-webui:8080` and `mcp-proxy:8000` via Docker network
- n8n points to remote hosted instance via `N8N_API_URL` env var
- Loki unavailable locally — handler degrades gracefully
- Voice bot auto-starts if `DISCORD_BOT_TOKEN` + `ELEVENLABS_API_KEY` are set

### 2. Update `.env.example`
Add all webhook-handler, Discord, ElevenLabs, and n8n vars with placeholder values so devs know what to configure.

### 3. No code changes needed
- webhook-handler config already defaults to Docker internal URLs
- Voice bot already handles missing vars gracefully
- Loki client already wraps calls in try/except

## What Does NOT Change
- Caddyfile (production only)
- API Gateway (production only)
- n8n (remote hosted, not local)
- webhook-handler source code
- Grafana/Loki/Promtail (production only)

## Success Criteria
- `docker compose up -d` starts all services including webhook-handler
- webhook-handler logs show "ready on port 8086"
- Discord bot commands work (if Discord vars are set)
- `/aiui ask` routes to OpenWebUI and returns AI answers
- Voice bot starts if ElevenLabs vars are present
