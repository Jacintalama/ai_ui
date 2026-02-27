# Error & Crash Logging — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add centralized error/crash logging with Grafana Loki + Grafana dashboards and Discord alerts, so the team knows when things break without SSH'ing into the server.

**Architecture:** Docker Loki log driver captures stdout/stderr from all containers automatically (zero code changes). Loki stores and indexes logs. Grafana queries Loki for dashboards and fires Discord webhook alerts on error patterns.

**Tech Stack:** Grafana Loki 3.4, Grafana 11.5.2, Docker Loki log driver plugin, Caddy reverse proxy, Discord webhooks

**Design doc:** `docs/plans/2026-02-27-error-logging-design.md`

---

## Context — Current State

| What | Where |
|------|-------|
| Docker Compose | `docker-compose.unified.yml` (22 services, 2 networks, 8 volumes) |
| Reverse proxy | `Caddyfile` (port 80, routes to api-gateway + open-webui) |
| Server | Hetzner VPS at `46.224.193.25`, user `root` |
| Deploy path | `/root/proxy-server/` |
| Discord | `#dev-notifications` channel already exists |
| Existing logging | Each container logs to stdout → Docker `json-file` driver (local only, no aggregation) |

---

### Task 1: Install Docker Loki log driver plugin on Hetzner

The Loki Docker log driver is a Docker plugin that ships container logs to Loki. Must be installed on the host before any container can use `logging.driver: loki`.

**Files:** None (server-side only)

**Step 1: SSH into server and install the plugin**

```bash
ssh root@46.224.193.25 "docker plugin install grafana/loki-docker-driver:3.4.2 --alias loki --grant-all-permissions"
```

Expected: `3.4.2: Pulling ... Installed plugin grafana/loki-docker-driver:3.4.2`

**Step 2: Verify plugin is installed and enabled**

```bash
ssh root@46.224.193.25 "docker plugin ls"
```

Expected: Shows `loki:latest` with `true` in Enabled column.

**Step 3: Commit** (nothing to commit — server-side only)

---

### Task 2: Add Loki service to docker-compose.unified.yml

Loki is the log aggregation backend. It receives logs from the Docker plugin and stores them.

**Files:**
- Modify: `docker-compose.unified.yml` (add service + volume)

**Step 1: Add Loki config file**

Create `loki/loki-config.yaml` with local storage, 7-day retention, and sensible defaults:

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 168h  # 7 days

compactor:
  working_directory: /loki/compactor
  retention_enabled: true
  delete_request_store: filesystem
```

**Step 2: Add `loki` service to `docker-compose.unified.yml`**

Insert after the `pipelines` service block (before `networks:` section):

```yaml
  # ===========================================================================
  # LOKI - Log Aggregation
  # ===========================================================================
  # Receives logs from Docker Loki log driver. Stores and indexes by container.
  loki:
    image: grafana/loki:3.4
    container_name: loki
    restart: unless-stopped
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - ./loki/loki-config.yaml:/etc/loki/local-config.yaml:ro
      - loki-data:/loki
    networks:
      - backend
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--output-document=-", "http://localhost:3100/ready"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Step 3: Add `loki-data` volume**

In the `volumes:` section at the bottom, add:

```yaml
  loki-data:
```

**Step 4: Commit**

```bash
git add loki/loki-config.yaml docker-compose.unified.yml
git commit -m "feat: add Loki log aggregation service"
```

---

### Task 3: Add Grafana service to docker-compose.unified.yml

Grafana provides the web dashboard for searching logs and configuring alerts.

**Files:**
- Modify: `docker-compose.unified.yml` (add service + volume)
- Create: `grafana/provisioning/datasources/loki.yaml` (auto-configure Loki data source)

**Step 1: Create Grafana provisioning config**

Create `grafana/provisioning/datasources/loki.yaml`:

```yaml
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: true
```

This auto-adds Loki as a data source when Grafana starts — no manual setup needed.

**Step 2: Add `grafana` service to `docker-compose.unified.yml`**

Insert after the `loki` service block:

```yaml
  # ===========================================================================
  # GRAFANA - Log Dashboard + Alerts
  # ===========================================================================
  # Web UI for searching logs, viewing dashboards, and configuring alerts.
  # Access via /grafana/ route in Caddy.
  grafana:
    image: grafana/grafana:11.5.2
    container_name: grafana
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
      - GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana/
      - GF_SERVER_SERVE_FROM_SUB_PATH=true
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      - loki
    networks:
      - backend
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--output-document=-", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

Key config:
- `GF_SERVER_ROOT_URL` + `GF_SERVER_SERVE_FROM_SUB_PATH=true` — Required for Grafana to work behind `/grafana/` sub-path in Caddy
- `GRAFANA_ADMIN_PASSWORD` — Set in `.env` on server, defaults to `admin` if unset

**Step 3: Add `grafana-data` volume**

In the `volumes:` section, add:

```yaml
  grafana-data:
```

**Step 4: Commit**

```bash
git add grafana/provisioning/datasources/loki.yaml docker-compose.unified.yml
git commit -m "feat: add Grafana dashboard with auto-provisioned Loki datasource"
```

---

### Task 4: Add logging driver to all services

Configure every existing service to send logs to Loki via the Docker log driver plugin.

**Files:**
- Modify: `docker-compose.unified.yml` (add `logging:` block to each service)

**Step 1: Add `x-logging` anchor at the top of the file**

Insert right after `services:` line (line 25), before the first service definition:

```yaml
  x-logging: &loki-logging
    driver: loki
    options:
      loki-url: "http://localhost:3100/loki/api/v1/push"
      loki-retries: "3"
      loki-batch-size: "100"
      labels: "container_name"
```

Using a YAML anchor (`&loki-logging`) means we define the config once and reference it with `*loki-logging` on every service.

**Step 2: Add `logging: *loki-logging` to every service**

Add `logging: *loki-logging` to each of these services:
- `caddy`
- `api-gateway`
- `webhook-handler`
- `n8n`
- `mcp-proxy`
- `open-webui`
- `admin-portal`
- `postgres`
- `redis`
- `mcp-filesystem`
- `mcp-github`
- `mcp-clickup`
- `mcp-trello`
- `mcp-sonarqube`
- `mcp-excel`
- `mcp-dashboard`
- `mcp-notion`
- `mcp-n8n`
- `mcp-scheduler`
- `pipelines`

Do NOT add logging to `db-init` (runs once and exits) or `loki`/`grafana` (would create a circular dependency).

Example for each service:

```yaml
  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    logging: *loki-logging     # <-- add this line
    ports:
      ...
```

**Step 3: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add Loki log driver to all services via YAML anchor"
```

---

### Task 5: Add Caddy route for Grafana

Expose Grafana at `https://ai-ui.coolestdomain.win/grafana/` through the existing Caddy reverse proxy.

**Files:**
- Modify: `Caddyfile` (add `/grafana/*` route)

**Step 1: Add Grafana route to Caddyfile**

Insert a new `handle` block after the n8n block (around line 112) and before the static assets block:

```
	# ---------------------------------------------------------------------------
	# Grafana - Log Dashboard (bypass gateway, direct to grafana)
	# ---------------------------------------------------------------------------
	handle /grafana/* {
		reverse_proxy grafana:3000
	}
```

This goes BEFORE the `handle /*` catch-all at the bottom. Grafana bypasses the API Gateway (no JWT needed for Grafana — it has its own auth).

**Step 2: Commit**

```bash
git add Caddyfile
git commit -m "feat: add Caddy route for Grafana at /grafana/"
```

---

### Task 6: Deploy to Hetzner and verify stack starts

Push the changes to the server and bring up the new containers.

**Files:** None (deployment commands only)

**Step 1: SCP updated files to server**

```bash
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
scp Caddyfile root@46.224.193.25:/root/proxy-server/Caddyfile
scp -r loki/ root@46.224.193.25:/root/proxy-server/loki/
scp -r grafana/ root@46.224.193.25:/root/proxy-server/grafana/
```

**Step 2: Bring up new containers first (Loki must be running before other containers restart)**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d loki grafana"
```

Wait 10 seconds for Loki to become ready.

**Step 3: Verify Loki is healthy**

```bash
ssh root@46.224.193.25 "docker exec loki wget -q -O- http://localhost:3100/ready"
```

Expected: `ready`

**Step 4: Recreate all other containers (picks up new logging driver)**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --force-recreate caddy"
```

Then recreate remaining services:

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d"
```

**Step 5: Verify Grafana is accessible**

```bash
curl -s -o /dev/null -w "%{http_code}" https://ai-ui.coolestdomain.win/grafana/login
```

Expected: `200`

**Step 6: Verify logs are flowing to Loki**

```bash
ssh root@46.224.193.25 "docker exec loki wget -q -O- 'http://localhost:3100/loki/api/v1/label/container_name/values'"
```

Expected: JSON array containing container names like `["api-gateway","caddy","open-webui",...]`

---

### Task 7: Configure Grafana dashboard and Discord alerts

Set up the error dashboard and alert rules via the Grafana API.

**Files:** None (Grafana API configuration)

**Step 1: Verify Grafana login works**

```bash
curl -s -u admin:${GRAFANA_ADMIN_PASSWORD:-admin} \
  https://ai-ui.coolestdomain.win/grafana/api/org
```

Expected: JSON with org name.

**Step 2: Create Discord contact point for alerts**

```bash
ssh root@46.224.193.25 'curl -s -X POST http://localhost:3000/grafana/api/v1/provisioning/contact-points \
  -H "Content-Type: application/json" \
  -u admin:${GRAFANA_ADMIN_PASSWORD:-admin} \
  -d '"'"'{
    "name": "Discord Dev Notifications",
    "type": "discord",
    "settings": {
      "url": "'"${DISCORD_WEBHOOK_URL}"'",
      "message": "{{ template \"default.message\" . }}"
    }
  }'"'"''
```

Note: `DISCORD_WEBHOOK_URL` must be set in `.env` on the server. This is the webhook URL for the `#dev-notifications` Discord channel.

**Step 3: Create alert rules**

Create 4 alert rules via Grafana API:

**Rule 1: Container crash detection**
- LogQL: `count_over_time({container_name=~".+"} |= "container exited" or "OOMKilled" or "exit code" [5m]) > 0`
- Severity: critical

**Rule 2: HTTP 500 errors**
- LogQL: `count_over_time({container_name="api-gateway"} |~ "status[=:]5[0-9]{2}" [5m]) > 5`
- Severity: critical

**Rule 3: High error rate (any service)**
- LogQL: `count_over_time({container_name=~".+"} |~ "(?i)(error|exception|traceback|panic)" [5m]) > 20`
- Severity: warning

**Rule 4: Auth failure spike**
- LogQL: `count_over_time({container_name=~"api-gateway|open-webui"} |~ "(?i)(unauthorized|forbidden|401|403)" [5m]) > 10`
- Severity: warning

These will be created via `POST /grafana/api/v1/provisioning/alert-rules`.

**Step 4: Set Discord as default notification policy**

```bash
ssh root@46.224.193.25 'curl -s -X PUT http://localhost:3000/grafana/api/v1/provisioning/policies \
  -H "Content-Type: application/json" \
  -u admin:${GRAFANA_ADMIN_PASSWORD:-admin} \
  -d '"'"'{
    "receiver": "Discord Dev Notifications",
    "group_by": ["alertname"],
    "group_wait": "30s",
    "group_interval": "5m",
    "repeat_interval": "4h"
  }'"'"''
```

**Step 5: Commit** (nothing to commit — Grafana API config)

---

### Task 8: Test end-to-end

Verify the full pipeline works: generate an error → see it in Grafana → verify alert fires.

**Files:** None (testing only)

**Step 1: Generate a test error**

```bash
ssh root@46.224.193.25 "docker exec api-gateway python3 -c \"import logging; logging.error('TEST ERROR: Verifying Loki integration')\""
```

**Step 2: Query Loki for the test error**

```bash
ssh root@46.224.193.25 "docker exec loki wget -q -O- 'http://localhost:3100/loki/api/v1/query?query=%7Bcontainer_name%3D%22api-gateway%22%7D%20%7C%3D%20%22TEST%20ERROR%22'"
```

Expected: JSON result containing `"TEST ERROR: Verifying Loki integration"`

**Step 3: Open Grafana dashboard in browser**

Navigate to: `https://ai-ui.coolestdomain.win/grafana/`

- Login: `admin` / `${GRAFANA_ADMIN_PASSWORD}`
- Go to Explore → Select Loki data source
- Query: `{container_name="api-gateway"} |= "TEST ERROR"`
- Verify the test error appears

**Step 4: Verify alert rules exist**

```bash
ssh root@46.224.193.25 'curl -s http://localhost:3000/grafana/api/v1/provisioning/alert-rules \
  -u admin:${GRAFANA_ADMIN_PASSWORD:-admin}' | python3 -m json.tool | head -30
```

Expected: JSON array with 4 alert rules.

**Step 5: Commit all remaining changes and push**

```bash
git add -A
git commit -m "feat: add Loki + Grafana error logging with Discord alerts

- Loki log aggregation (all containers)
- Grafana dashboard at /grafana/
- Discord alerts for crashes, 500s, error spikes, auth failures
- 7-day log retention
- Auto-provisioned Loki datasource"
```

---

## Summary

| Task | What | New Files | Containers Affected |
|------|------|-----------|-------------------|
| 1 | Install Loki Docker plugin | None (server) | Host |
| 2 | Add Loki service | `loki/loki-config.yaml`, compose | +1 new |
| 3 | Add Grafana service | `grafana/provisioning/datasources/loki.yaml`, compose | +1 new |
| 4 | Add log driver to all services | compose | All 20 existing |
| 5 | Add Caddy route | `Caddyfile` | caddy |
| 6 | Deploy to Hetzner | None | All |
| 7 | Configure dashboard + alerts | None (API) | grafana |
| 8 | Test end-to-end | None | None |

**Total new containers:** 2 (Loki, Grafana)
**Estimated additional RAM:** ~300MB
**New env var needed:** `GRAFANA_ADMIN_PASSWORD`, `DISCORD_WEBHOOK_URL`
