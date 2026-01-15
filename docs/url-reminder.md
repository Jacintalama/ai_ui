# URL Reminder - Kubernetes vs Docker

**Date:** January 9, 2026

---

## Your System (Jacint) - KUBERNETES

| Service | URL |
|---------|-----|
| **Open WebUI** | http://localhost:30080 |
| **MCP Proxy** | http://localhost:30800 |

### MCP Proxy Endpoints

| Endpoint | URL | Returns |
|----------|-----|---------|
| Root `/` | http://localhost:30800/ | `{"detail": "Not Found"}` (normal!) |
| Health | http://localhost:30800/health | ✅ Status |
| Servers | http://localhost:30800/servers | ✅ 11 servers |
| GitHub | http://localhost:30800/github | ✅ 40 tools |
| Filesystem | http://localhost:30800/filesystem | ✅ 14 tools |
| Linear | http://localhost:30800/linear | ⏳ Needs API key |
| Notion | http://localhost:30800/notion | ⏳ Needs API key |

**Note:** `http://localhost:30800/` returns "Not Found" - this is **normal**! Use `/servers` or `/github` instead.

---

## Lukas's System (Client) - DOCKER

| Service | URL |
|---------|-----|
| **Open WebUI** | http://localhost:3000 |
| **MCP Proxy** | http://localhost:8000 |

### MCP Proxy Endpoints (Docker)

| Endpoint | URL |
|----------|-----|
| Health | http://localhost:8000/health |
| Servers | http://localhost:8000/servers |
| GitHub | http://localhost:8000/github |
| Filesystem | http://localhost:8000/filesystem |

---

## Quick Reference

```
┌─────────────────────────────────────────────────────┐
│                    JACINT (You)                     │
│                    KUBERNETES                       │
├─────────────────────────────────────────────────────┤
│  Open WebUI:  http://localhost:30080                │
│  MCP Proxy:   http://localhost:30800/servers        │
│               http://localhost:30800/github         │
│               http://localhost:30800/filesystem     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    LUKAS (Client)                   │
│                    DOCKER                           │
├─────────────────────────────────────────────────────┤
│  Open WebUI:  http://localhost:3000                 │
│  MCP Proxy:   http://localhost:8000/servers         │
│               http://localhost:8000/github          │
│               http://localhost:8000/filesystem      │
└─────────────────────────────────────────────────────┘
```

---

## Commands

### Kubernetes (You)
```bash
# Check pods
kubectl get pods -n open-webui

# Check services
kubectl get svc -n open-webui

# Deploy
cd kubernetes
.\deploy.ps1
```

### Docker (Lukas)
```bash
# Start
docker compose up -d

# Stop
docker compose down
```

---

## Port Mapping

| Service | Kubernetes | Docker |
|---------|------------|--------|
| Open WebUI | 30080 | 3000 |
| MCP Proxy | 30800 | 8000 |
| PostgreSQL | 5433 (forwarded) | 5432 |
