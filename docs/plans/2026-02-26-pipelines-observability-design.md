# Pipelines + Observability — Research & Design

**Date:** 2026-02-26
**Status:** Implemented
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
| Observability | LangFuse Cloud free tier + in-process filter | +0 | ~0 |
| **Total** | | **+1 container** | **~200MB** |

---

## Architecture

### Before

```
Browser ──> Caddy ──> API Gateway ──> Open WebUI ──> OpenAI API (gpt-5)
                                        |
                                        ├── webhook_pipe.py (runs inside, no isolation)
                                        └── MCP Proxy / n8n
```

Everything ran inside Open WebUI. No observability. If webhook_pipe crashed, Open WebUI crashed.

### After

```
┌─────────┐    ┌───────┐    ┌─────────────┐    ┌──────────────────────────────────┐
│ Browser │───>│ Caddy │───>│ API Gateway │───>│         Open WebUI               │
└─────────┘    └───────┘    └─────────────┘    │                                  │
                                                │  ┌────────────────────────────┐  │
                                                │  │  LangFuse Filter (global)  │  │
                                                │  │                            │  │
                                                │  │  inlet() ──> before LLM    │  │
                                                │  │  outlet() ──> after LLM    │  │
                                                │  └──────────┬─────────────────┘  │
                                                │             │                    │
                                                └─────────────┼────────────────────┘
                                                    │         │
                                          ┌─────────┘         │
                                          ▼                   ▼
                                ┌──────────────────┐  ┌──────────────────┐
                                │ Pipelines :9099  │  │  LangFuse Cloud  │
                                │                  │  │  (us.cloud.      │
                                │  webhook_pipe.py │  │   langfuse.com)  │
                                │  (isolated)      │  │                  │
                                └────────┬─────────┘  │  ● Token usage   │
                                         │            │  ● Cost tracking │
                                         ▼            │  ● Traces        │
                                ┌──────────────────┐  │  ● Latency       │
                                │ MCP Proxy / n8n  │  └──────────────────┘
                                └──────────────────┘
```

### How a Chat Message Flows

```
1. You type "What is the capital of France?" in the browser

2. Browser ──POST──> /api/chat/completions
       │
       ▼
3. ┌─ INLET fires (LangFuse Filter) ──────────────────────────┐
   │  • Creates a trace in LangFuse Cloud                      │
   │  • Records: user email, model (gpt-5), chat ID, prompt   │
   └───────────────────────────────────────────────────────────┘
       │
       ▼
4. Open WebUI forwards to OpenAI API ──> gpt-5 responds "Paris"
       │
       ▼
5. Response streams back to browser (you see "Paris")
       │
       ▼
6. Browser ──POST──> /api/chat/completed  (automatic, invisible)
       │
       ▼
7. ┌─ OUTLET fires (LangFuse Filter) ─────────────────────────┐
   │  • Captures AI response ("Paris")                         │
   │  • Captures token count (29 input, 1 output)             │
   │  • Creates a GENERATION observation in LangFuse           │
   │  • Flushes to LangFuse Cloud                             │
   └───────────────────────────────────────────────────────────┘
       │
       ▼
8. LangFuse Dashboard shows the full trace:
   model=gpt-5 | user=you | tokens=30 | output="Paris"
```

### Why the LangFuse Filter Runs In-Process

Open WebUI only calls `outlet()` on **in-process** filter functions (installed inside Open WebUI itself). External Pipelines filters only get `inlet()` calls — the `outlet()` endpoint exists but Open WebUI never calls it. Since we need the outlet to capture responses and token counts, the LangFuse filter must run in-process.

The Pipelines container is still used for `webhook_pipe.py` which benefits from process isolation (heavy MCP tool chains, arbitrary dependencies).

### Key Files

| File | Location | Purpose |
|------|----------|---------|
| `langfuse_filter.py` | In-process (Open WebUI Functions) | Global filter: traces all LLM calls to LangFuse |
| `webhook_pipe.py` | Pipelines container (`/app/pipelines/`) | Webhook automation pipe (MCP tools + n8n) |
| `docker-compose.unified.yml` | Repo + server | Defines pipelines service + env vars |

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
- One code change needed: `class Pipe` must be renamed to `class Pipeline` (external Pipelines server expects `Pipeline`, Open WebUI in-process expects `Pipe`)

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

`langfuse_filter.py` runs as an **in-process global filter** inside Open WebUI (not in the Pipelines container):

- `inlet()` — Runs before every LLM call. Creates a trace with user ID, model, chat ID.
- `outlet()` — Runs after every LLM call. Captures token count, response. Sends to LangFuse.

Applies to ALL models, not just the webhook pipe. Installed via Admin Panel -> Workspace -> Functions.

### Configuration (Valves in Admin Panel)

| Valve | Value |
|-------|-------|
| `public_key` | `pk-lf-ecd2a5fa-c51e-4cb0-a125-88de3b03e51e` |
| `secret_key` | `sk-lf-d5d3f40b-ce6c-444f-acc5-1d8422654d8f` |
| `host` | `https://us.cloud.langfuse.com` |
| `pipelines` | `["*"]` (all models) |
| `debug` | `false` (set `true` to see `[LangFuse]` logs) |

### Free Tier Limits

- 50k observations/month (1 observation = 1 LLM call)
- Sufficient for current platform usage

### Environment Variables (`.env` + `docker-compose.unified.yml`)

```
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"
```

These are passed to the Open WebUI container as `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST`. The filter reads them on first use (lazy init).

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

## 4. Setup Steps (What Was Done)

1. Added `pipelines` service to `docker-compose.unified.yml` with `pipelines-data` volume
2. Added `OPENAI_API_KEYS` / `OPENAI_API_BASE_URLS` (semicolon-separated) to Open WebUI env for Pipelines connection
3. Added `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` env vars to Open WebUI container
4. Deployed to Hetzner: `docker compose up -d pipelines`
5. Moved `webhook_pipe.py` into Pipelines container (renamed `class Pipe` to `class Pipeline`)
6. Installed `langfuse_filter.py` as in-process global filter in Open WebUI via API
7. Configured LangFuse valves (API keys, host, debug mode)
8. Tested from browser chat — inlet + outlet both fire, traces visible in LangFuse Cloud

---

## 5. Future Upgrades (Not Now)

- **Self-host LangFuse** — If free tier limits are hit or data privacy requires it (6 containers, ~2GB RAM)
- **OpenTelemetry** — Enable Open WebUI's `ENABLE_OTEL=true` for infrastructure-level metrics alongside LangFuse's LLM metrics
- **Custom Pipes** — Build additional pipes for RAG, async workflows, or LangGraph integration
