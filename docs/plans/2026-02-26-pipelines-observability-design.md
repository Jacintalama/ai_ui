# Pipelines + Observability — Research & Design

**Date:** 2026-02-26
**Status:** Approved
**Origin:** Lukas standup review (2026-02-25) — "looking into pipelines and observability would be good areas"

---

## Context

Lukas identified two areas to explore:

1. **Open WebUI Pipelines** — Offload heavy/long-running work (e.g., MCP tool chains that make the chat wait) to a separate process
2. **Observability** — Logging, seeing how people use the platform, token usage, costs

The platform already runs ~15 containers on a Hetzner VPS. Both solutions must be lightweight.

---

## Decisions

| Area | Chosen Approach | New Containers | RAM |
|------|----------------|---------------|-----|
| Pipelines | External Pipelines container | +1 | ~200MB |
| Observability | LangFuse Cloud free tier + filter | +0 (uses Pipelines) | ~0 |
| **Total** | | **+1 container** | **~200MB** |

---

## Architecture

### Before (Current)

```
Browser -> Caddy -> API Gateway -> Open WebUI (webhook_pipe.py runs inside)
                                       |
                                   MCP Proxy / n8n
```

### After

```
Browser -> Caddy -> API Gateway -> Open WebUI
                                       |
                                   Pipelines container (port 9099)
                                     |-- webhook_pipe.py (moved here)
                                     |-- langfuse_v3_filter_pipeline.py (new)
                                       |
                                   MCP Proxy / n8n
                                       |
                                   LangFuse Cloud (us.cloud.langfuse.com)
```

No Caddy changes needed. Pipelines only communicates internally on the Docker network.

---

## 1. Pipelines Container

### What It Is

Open WebUI Pipelines (`ghcr.io/open-webui/pipelines:main`) is a separate Docker container that runs Pipe Functions and Filters outside the main Open WebUI process. It exposes an OpenAI-compatible API on port 9099.

### Why It Matters

- **Process isolation** — If a heavy MCP tool chain crashes, Open WebUI keeps running
- **Arbitrary dependencies** — Can install any Python package (langchain, mcp SDK, ML models)
- **Independent scaling** — Separate CPU/memory limits via Docker `deploy.resources`

### Docker Compose Addition

```yaml
pipelines:
  image: ghcr.io/open-webui/pipelines:main
  container_name: pipelines
  restart: unless-stopped
  volumes:
    - pipelines-data:/app/pipelines
  environment:
    - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
    - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
    - LANGFUSE_BASE_URL=${LANGFUSE_BASE_URL}
  networks:
    - backend
```

New volume: `pipelines-data`

### How Open WebUI Connects

Add Pipelines as an OpenAI-compatible API connection:
- Admin Panel -> Settings -> Connections -> Add OpenAI API
- URL: `http://pipelines:9099`
- API Key: `0p3n-w3bu!` (default)

Every pipe in the container appears as a selectable "model" in the chat dropdown.

### What Moves There

- `webhook_pipe.py` — Copied into the Pipelines volume, auto-loaded on startup
- No code changes needed — the Pipe class API is identical between in-process and external

---

## 2. Observability (LangFuse Cloud)

### What It Is

LangFuse is an open-source (MIT) LLM observability platform. The cloud free tier at `us.cloud.langfuse.com` provides a dashboard for monitoring all LLM interactions without self-hosting any infrastructure.

### What You See

- Token usage per model, per user, per day
- Cost breakdown (configure model pricing in LangFuse)
- Latency per conversation (end-to-end, time-to-first-token)
- Full conversation traces (prompts in, responses out)
- User session tracking (who uses what, how often)

### How It Integrates

The official `langfuse_v3_filter_pipeline.py` runs as a Filter in the Pipelines container:

- `inlet()` — Runs before every LLM call. Creates a trace with user ID, model, chat ID.
- `outlet()` — Runs after every LLM call. Captures token count, latency, response. Sends to LangFuse.

Applies to ALL models, not just the webhook pipe.

### Configuration (Valves in Admin Panel)

| Valve | Value |
|-------|-------|
| `public_key` | `pk-lf-ecd2a5fa-c51e-4cb0-a125-88de3b03e51e` |
| `secret_key` | `sk-lf-d5d3f40b-ce6c-444f-acc5-1d8422654d8f` |
| `host` | `https://us.cloud.langfuse.com` |
| `pipelines` | `["*"]` (all models) |

### Free Tier Limits

- 50k observations/month (1 observation = 1 LLM call)
- Sufficient for current platform usage

### Environment Variables (`.env`)

```
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"
```

---

## 3. Alternatives Considered

### Pipelines

| Approach | Description | Verdict |
|----------|------------|---------|
| **A: External Pipelines container** | Official Open WebUI project, 1 container | **Chosen** |
| B: Keep current setup | webhook_pipe.py stays inside Open WebUI | Works today but no isolation |
| C: Custom worker service | Build own async task runner (Celery/Redis) | Overkill, reinvents Pipelines |

### Observability

| Approach | Description | Verdict |
|----------|------------|---------|
| **A: LangFuse Cloud free tier** | Zero containers, API keys + filter | **Chosen** |
| B: LangFuse self-hosted | 6 new containers, ~1.5-2GB RAM | Too heavy for current VPS |
| C: DIY with existing Postgres | Extend API Gateway analytics table | Basic, no rich dashboard |

---

## 4. Setup Steps

1. Add `pipelines` service to `docker-compose.unified.yml`
2. Add `pipelines-data` volume
3. Deploy to Hetzner: `docker compose -f docker-compose.unified.yml up -d pipelines`
4. Connect Open WebUI to Pipelines: Admin Panel -> Settings -> Connections -> Add OpenAI API (`http://pipelines:9099`, key: `0p3n-w3bu!`)
5. Install LangFuse filter: Upload `langfuse_v3_filter_pipeline.py` via Admin Panel -> Pipelines, configure Valves
6. Move `webhook_pipe.py` into Pipelines volume, verify it appears as a selectable model
7. Test: Send a chat message, check LangFuse dashboard for the trace
8. Sync `.env` to Hetzner server with LangFuse keys

---

## 5. Future Upgrades (Not Now)

- **Self-host LangFuse** — If free tier limits are hit or data privacy requires it (6 containers, ~2GB RAM)
- **OpenTelemetry** — Enable Open WebUI's `ENABLE_OTEL=true` for infrastructure-level metrics alongside LangFuse's LLM metrics
- **Custom Pipes** — Build additional pipes for RAG, async workflows, or LangGraph integration
