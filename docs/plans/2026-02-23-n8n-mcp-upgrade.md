# n8n-mcp Upgrade: npm to Official Docker Image

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the existing mcp-n8n service from npm-installed `n8n-mcp` (on node:20-slim + mcpo) to the official `ghcr.io/czlonkowski/n8n-mcp:latest` Docker image with native HTTP mode — faster startup, better-sqlite3, auto-updates, no mcpo dependency.

**Architecture:** Replace the current Dockerfile (node:20-slim + pip mcpo + npm n8n-mcp) with the pre-built `ghcr.io/czlonkowski/n8n-mcp:latest` image running in HTTP mode on port 3000. The mcp-proxy already connects to mcp-n8n; we just update the port mapping. Since the official image exposes an MCP HTTP endpoint (not OpenAPI), we keep mcpo as a thin wrapper for OpenAPI compatibility with mcp-proxy.

**Tech Stack:** Docker, ghcr.io/czlonkowski/n8n-mcp, mcpo, n8n API

---

### Task 1: Update the Dockerfile

**Files:**
- Modify: `mcp-servers/n8n/Dockerfile`

**Step 1: Read current Dockerfile**

Current:
```dockerfile
FROM node:20-slim
RUN apt-get update && apt-get install -y python3 python3-pip curl --no-install-recommends \
    && pip3 install --break-system-packages mcpo \
    && npm install -g n8n-mcp \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
EXPOSE 8000
CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCP_API_KEY\" -- npx n8n-mcp"]
```

**Step 2: Replace with official image + mcpo wrapper**

```dockerfile
# mcp-servers/n8n/Dockerfile
# n8n MCP Server (czlonkowski/n8n-mcp) with mcpo OpenAPI wrapper
# Uses official pre-built image: Node 22, better-sqlite3, 1084 node docs
# Source: https://github.com/czlonkowski/n8n-mcp (13.7k stars)
FROM ghcr.io/czlonkowski/n8n-mcp:latest

USER root

# Install mcpo for OpenAPI compatibility with mcp-proxy
RUN apk add --no-cache python3 py3-pip && \
    pip3 install --break-system-packages mcpo

USER nodejs

EXPOSE 8000

# Run in stdio mode through mcpo (converts MCP stdio → OpenAPI HTTP)
CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCP_API_KEY\" -- node /app/dist/mcp/index.js"]
```

**Why this approach:**
- Official image has pre-built better-sqlite3 (100x faster than sql.js WASM)
- Node 22 (matches upstream)
- Pre-compiled TypeScript, no build step needed
- SQLite node database pre-populated with 1,084 n8n nodes
- mcpo still needed because mcp-proxy expects OpenAPI endpoints

**Step 3: Commit**

```bash
git add mcp-servers/n8n/Dockerfile
git commit -m "chore: upgrade mcp-n8n to official Docker image"
```

---

### Task 2: Update docker-compose.unified.yml

**Files:**
- Modify: `docker-compose.unified.yml` (mcp-n8n service, ~lines 437-451)

**Step 1: Update the service definition**

Current:
```yaml
mcp-n8n:
  build: ./mcp-servers/n8n
  container_name: mcp-n8n
  restart: unless-stopped
  environment:
    - MCP_MODE=stdio
    - N8N_API_URL=${N8N_API_URL:-https://n8n.srv1041674.hstgr.cloud}
    - N8N_API_KEY=${N8N_API_KEY:-}
    - MCP_API_KEY=${MCP_API_KEY:-mcp-secret-key}
    - LOG_LEVEL=error
    - DISABLE_CONSOLE_OUTPUT=true
    - N8N_MCP_TELEMETRY_DISABLED=true
  networks:
    - backend
```

Replace with:
```yaml
# n8n MCP - AI-driven workflow creation and management (20 tools)
# Official image: ghcr.io/czlonkowski/n8n-mcp (13.7k stars)
mcp-n8n:
  build: ./mcp-servers/n8n
  container_name: mcp-n8n
  restart: unless-stopped
  environment:
    - MCP_MODE=stdio
    - N8N_API_URL=${N8N_API_URL:-https://n8n.srv1041674.hstgr.cloud}
    - N8N_API_KEY=${N8N_API_KEY:-}
    - MCP_API_KEY=${MCP_API_KEY:-mcp-secret-key}
    - LOG_LEVEL=error
    - DISABLE_CONSOLE_OUTPUT=true
    - N8N_MCP_TELEMETRY_DISABLED=true
    - NODE_ENV=production
    - REBUILD_ON_START=false
  volumes:
    - n8n-mcp-data:/app/data
  deploy:
    resources:
      limits:
        memory: 512M
      reservations:
        memory: 256M
  networks:
    - backend
```

**Step 2: Add volume to the volumes section at bottom of file**

Add to volumes:
```yaml
  n8n-mcp-data:
```

**Step 3: Commit**

```bash
git add docker-compose.unified.yml
git commit -m "feat: add persistent volume and memory limits to mcp-n8n"
```

---

### Task 3: Deploy to Server

**Step 1: Copy updated files to server**

```bash
scp mcp-servers/n8n/Dockerfile root@46.224.193.25:/root/proxy-server/mcp-servers/n8n/Dockerfile
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

**Step 2: Rebuild the mcp-n8n container**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build mcp-n8n"
```

Expected: Container pulls `ghcr.io/czlonkowski/n8n-mcp:latest`, installs mcpo, starts up.

**Step 3: Verify the container is running and tools are available**

```bash
ssh root@46.224.193.25 "docker logs mcp-n8n 2>&1 | tail -10"
ssh root@46.224.193.25 "docker exec mcp-n8n curl -s http://localhost:8000/openapi.json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f\"Tools: {len(d.get(\"paths\",{}))}\")"
```

Expected: `Tools: 20` (7 core docs + 13 n8n management)

**Step 4: Verify n8n API connectivity**

```bash
ssh root@46.224.193.25 "docker exec mcp-n8n curl -s http://localhost:8000/openapi.json | python3 -c '
import sys,json
d=json.load(sys.stdin)
paths = list(d.get(\"paths\",{}).keys())
print(f\"Total tools: {len(paths)}\")
for p in sorted(paths):
    print(f\"  {p}\")
'"
```

Expected: Should show tools like `n8n_create_workflow`, `n8n_list_workflows`, `search_nodes`, `validate_workflow`, etc.

---

### Task 4: Test from Open WebUI

**Step 1: Open Open WebUI at https://ai-ui.coolestdomain.win**

**Step 2: Start a chat and test n8n MCP tools**

Ask the AI: "List all active n8n workflows using MCP tools"

Expected: The AI should use the n8n_list_workflows tool to fetch and display workflows.

**Step 3: Test workflow creation capability**

Ask: "Create a simple n8n workflow that triggers on a schedule every hour and sends an HTTP request to https://httpbin.org/get"

Expected: The AI should use search_nodes to find the right nodes, then n8n_create_workflow to build it.

---

### Task 5: Verify via Discord Bot

**Step 1: Use the /aiui command in Discord**

```
/aiui mcp n8n n8n_list_workflows
```

Expected: Should return the list of workflows from n8n.

---

## Rollback Plan

If the new image fails, revert the Dockerfile:

```dockerfile
FROM node:20-slim
RUN apt-get update && apt-get install -y python3 python3-pip curl --no-install-recommends \
    && pip3 install --break-system-packages mcpo \
    && npm install -g n8n-mcp \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
EXPOSE 8000
CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCP_API_KEY\" -- npx n8n-mcp"]
```

Then rebuild: `docker compose -f docker-compose.unified.yml up -d --build mcp-n8n`
