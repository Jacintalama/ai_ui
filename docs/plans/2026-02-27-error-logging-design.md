# Error & Crash Logging — Research & Design

**Date:** 2026-02-27
**Status:** Approved
**Origin:** Lukas standup review (2026-02-26) — "if something goes wrong in the API, let's say in the proxy server or somewhere in WebUI, it will be next good thing to implement"

---

## Context

LangFuse tracks LLM usage (tokens, cost, who asked what). But there's no system-level error logging. If the API Gateway returns 500s, a container crashes, or Open WebUI throws an error — nobody knows until a user reports it.

Lukas wants: **when something breaks, see WHERE and WHY without SSH'ing into the server.**

He also mentioned: "I believe that it's in the docs, it supports some logging out of the box."

---

## Decisions

| Area | Chosen Approach | New Containers | RAM |
|------|----------------|---------------|-----|
| Log aggregation | Grafana Loki (self-hosted, free) | +1 | ~100MB |
| Dashboard + alerts | Grafana (self-hosted, free) | +1 | ~200MB |
| Notifications | Discord webhook to #dev-notifications | +0 | ~0 |
| **Total** | | **+2 containers** | **~300MB** |

---

## Architecture

### Before (Current)

```
All containers ──> stdout/stderr ──> Docker logs (local only)
                                        |
                                     Only visible via SSH:
                                     $ docker logs api-gateway
                                     $ docker logs open-webui
                                     (no dashboard, no alerts, no search)
```

### After

```
┌──────────────────────────────────────────────────────────────────┐
│                     Hetzner VPS (Docker)                         │
│                                                                  │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ API Gateway │ │ Open     │ │Pipelines │ │ All other        │  │
│  │             │ │ WebUI    │ │          │ │ containers       │  │
│  └──────┬──────┘ └────┬─────┘ └────┬─────┘ └───────┬──────────┘  │
│         │             │            │               │             │
│         └──────┬──────┴────────────┴───────────────┘             │
│                │ (Docker log driver sends all stdout/stderr)     │
│                ▼                                                 │
│  ┌─────────────────────┐                                         │
│  │     Loki             │  Stores logs, indexes by container,    │
│  │     (port 3100)      │  label, time. Retention: 7 days.      │
│  └──────────┬──────────┘                                         │
│             │                                                    │
│             ▼                                                    │
│  ┌─────────────────────┐     ┌──────────────────────┐            │
│  │     Grafana          │────>│   Discord Webhook    │            │
│  │     (port 3001)      │     │   #dev-notifications │            │
│  │                      │     └──────────────────────┘            │
│  │  • Search all logs   │                                        │
│  │  • Filter by service │                                        │
│  │  • Error dashboards  │                                        │
│  │  • Alert rules       │                                        │
│  └─────────────────────┘                                         │
└──────────────────────────────────────────────────────────────────┘
```

### How It Works

```
1. Every container writes logs to stdout/stderr (already happens today)

2. Docker Loki log driver captures ALL container logs automatically
       │
       ▼
3. ┌─ Loki receives logs ─────────────────────────────────────┐
   │  • Indexes by container name, log level, timestamp       │
   │  • Stores for 7 days, then auto-deletes                  │
   │  • No code changes needed in any service                 │
   └──────────────────────────────────────────────────────────┘
       │
       ▼
4. ┌─ Grafana queries Loki ───────────────────────────────────┐
   │  • Dashboard shows errors per service                    │
   │  • Searchable log stream (filter by service, level, time)│
   │  • Click any log to see full context                     │
   └──────────────────────────────────────────────────────────┘
       │
       ▼
5. ┌─ Alert rules fire on error patterns ─────────────────────┐
   │  • Container crash → Discord alert (critical)            │
   │  • HTTP 500/502 → Discord alert (critical)               │
   │  • Auth failure spike → Discord alert (warning)          │
   │  • High error rate → Discord alert (warning)             │
   └──────────────────────────────────────────────────────────┘
       │
       ▼
6. Discord #dev-notifications shows:
   🔴 [CRITICAL] Container crash detected
     Service: pipelines
     Time: 2026-02-27 14:32:05
     Dashboard: https://ai-ui.coolestdomain.win/grafana/...
```

### Key Points

- **Zero code changes** to any service — Loki captures Docker stdout/stderr automatically
- **Every container** is covered (API Gateway, Open WebUI, Pipelines, n8n, MCP Proxy, Caddy, Redis, Postgres)
- **Grafana** is where you go to search logs and see errors
- **Discord alerts** fire when Grafana detects error patterns

---

## 1. Docker Compose Changes

### New Services

```yaml
# =====================================================
# Loki — Log Aggregator
# =====================================================
loki:
  image: grafana/loki:3.4
  container_name: loki
  restart: unless-stopped
  command: -config.file=/etc/loki/local-config.yaml
  volumes:
    - loki-data:/loki
  networks:
    - backend

# =====================================================
# Grafana — Log Dashboard + Alerts
# =====================================================
grafana:
  image: grafana/grafana:11.5.2
  container_name: grafana
  restart: unless-stopped
  ports:
    - "127.0.0.1:3001:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
  volumes:
    - grafana-data:/var/lib/grafana
  depends_on:
    - loki
  networks:
    - backend
```

### Log Driver on All Services

```yaml
# Added to each service (or as default logging driver)
logging:
  driver: loki
  options:
    loki-url: "http://localhost:3100/loki/api/v1/push"
    labels: "service"
```

### New Volumes

```yaml
volumes:
  loki-data:
  grafana-data:
```

### Caddy Route (access Grafana from browser)

```
/grafana/* → grafana:3000
```

---

## 2. Discord Alert Rules

| Rule | Trigger | Severity |
|------|---------|----------|
| Container crash | Any container exits/restarts | Critical |
| HTTP 500 errors | API Gateway logs contain `status=500` or `status=502` | Critical |
| Auth failures spike | More than 10 failed auth attempts in 5 min | Warning |
| High error rate | Any service logs more than 20 ERROR-level lines in 5 min | Warning |

### Discord Alert Format

```
🔴 [CRITICAL] Container crash detected
  Service: pipelines
  Time: 2026-02-27 14:32:05
  Message: Container restarted after exit code 1
  Dashboard: https://ai-ui.coolestdomain.win/grafana/...
```

---

## 3. Grafana Dashboard

Pre-configured dashboard showing:

- **Error count by service** (bar chart, last hour)
- **Live error log stream** (filterable by service, level, time)
- **Search** across all containers
- **Time range selector** (last 1h, 6h, 24h, 7d)

---

## 4. Alternatives Considered

| Approach | Description | Verdict |
|----------|------------|---------|
| **A: Loki + Grafana** | Self-hosted, free, covers all containers, dashboard + alerts | **Chosen** |
| B: Custom Discord Logger | Zero containers, just Python logging + Discord webhook | No dashboard, can't search logs, fragile for Open WebUI |
| C: Sentry Cloud | Amazing error detail but can't instrument Open WebUI, 5k/month limit | Too limited for full stack |

---

## 5. What This Gives You vs LangFuse

| | LangFuse (already have) | Loki + Grafana (adding) |
|---|---|---|
| **Tracks** | LLM calls (tokens, cost, latency) | System errors (crashes, 500s, failures) |
| **Answers** | "How much are we spending on AI?" | "Why is the API returning errors?" |
| **Scope** | Only LLM interactions | Every container in the stack |
| **Alerts** | None | Discord notifications on critical errors |

---

## 6. Setup Steps

1. Install Docker Loki log driver plugin on Hetzner server
2. Add `loki` and `grafana` services to `docker-compose.unified.yml`
3. Add `loki-data` and `grafana-data` volumes
4. Add `logging.driver: loki` to all existing services
5. Add Caddy route for `/grafana/`
6. Deploy and start containers
7. Configure Grafana: add Loki as data source
8. Create error dashboard
9. Set up Discord webhook as contact point
10. Create alert rules (container crash, 500 errors, auth spikes, high error rate)
11. Test: trigger an error, verify it shows in Grafana and Discord

---

## 7. Future Upgrades (Not Now)

- **Prometheus + node-exporter** — CPU, RAM, disk metrics alongside logs
- **Tempo** — Distributed tracing (correlate a single request across API Gateway → Open WebUI → Pipelines)
- **Log-based metrics** — Track request rates, error rates as time-series charts
