# Today's Implementation Plan - January 15, 2026

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update infrastructure for Open WebUI v0.7 with Redis, PostgreSQL+PGVector, and production-ready configuration.

**Architecture:** Multi-tenant Open WebUI with Redis for session management, PostgreSQL+PGVector for unified data storage, and MCP Proxy for tool access control.

**Tech Stack:** Docker Compose, Open WebUI v0.7, Redis, PostgreSQL 16 + PGVector, Entra ID OAuth

---

## Priority Overview

| # | Task | Time | Status |
|---|------|------|--------|
| 1 | Update Open WebUI to v0.7 | 5 min | |
| 2 | Add Redis for sessions/tenants | 10 min | |
| 3 | Add PostgreSQL + PGVector | 15 min | |
| 4 | Configure Entra ID OAuth | 10 min | |
| 5 | Test full stack | 10 min | |
| 6 | Deploy to Kubernetes | 15 min | |

---

## Task 1: Update Open WebUI to v0.7

**Files:**
- Modify: `docker-compose.yml:25-42`

**Step 1: Update Open WebUI image tag**

```yaml
open-webui:
  image: ghcr.io/open-webui/open-webui:v0.7.0
  container_name: open-webui
  ports:
    - "3000:8080"
```

**Step 2: Verify image exists**

Run: `docker pull ghcr.io/open-webui/open-webui:v0.7.0`
Expected: Image pulled successfully

---

## Task 2: Add Redis for Session Management

**Files:**
- Modify: `docker-compose.yml` (add Redis service)

**Step 1: Add Redis service to docker-compose.yml**

Add after the `ollama` service:

```yaml
  # ==========================================================================
  # Redis - Session & Cache Management
  # ==========================================================================
  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Step 2: Add Redis volume**

Add to volumes section:

```yaml
volumes:
  ollama-data:
  open-webui-data:
  redis-data:
```

**Step 3: Configure Open WebUI to use Redis**

Update open-webui environment:

```yaml
    environment:
      # ... existing vars ...
      # Redis for sessions and caching
      - REDIS_URL=redis://redis:6379/0
      - ENABLE_REDIS=true
```

**Step 4: Add Redis dependency**

```yaml
    depends_on:
      - ollama
      - redis
```

---

## Task 3: Add PostgreSQL + PGVector

**Files:**
- Modify: `docker-compose.yml` (add PostgreSQL service)

**Step 1: Add PostgreSQL service**

Add after Redis service:

```yaml
  # ==========================================================================
  # PostgreSQL + PGVector - Unified Database
  # ==========================================================================
  postgres:
    image: pgvector/pgvector:pg16
    container_name: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=openwebui
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-openwebui-secret}
      - POSTGRES_DB=openwebui
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U openwebui -d openwebui"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Step 2: Add PostgreSQL volume**

```yaml
volumes:
  ollama-data:
  open-webui-data:
  redis-data:
  postgres-data:
```

**Step 3: Configure Open WebUI to use PostgreSQL**

Update open-webui environment:

```yaml
    environment:
      # ... existing vars ...
      # PostgreSQL Database (replaces SQLite)
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      # Vector Database (PGVector instead of ChromaDB)
      - VECTOR_DB=pgvector
      - PGVECTOR_CONNECTION_STRING=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
```

**Step 4: Add PostgreSQL dependency**

```yaml
    depends_on:
      - ollama
      - redis
      - postgres
```

---

## Task 4: Configure Entra ID OAuth

**Files:**
- Modify: `docker-compose.yml` (open-webui environment)

**Step 1: Add Entra ID environment variables**

```yaml
    environment:
      # ... existing vars ...
      # Microsoft Entra ID OAuth
      - ENABLE_OAUTH_SIGNUP=true
      - OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
      - MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}
      - MICROSOFT_CLIENT_SECRET=${MICROSOFT_CLIENT_SECRET}
      - MICROSOFT_CLIENT_TENANT_ID=${MICROSOFT_CLIENT_TENANT_ID}
      # Group Management for Multi-Tenant
      - ENABLE_OAUTH_GROUP_MANAGEMENT=true
      - ENABLE_OAUTH_GROUP_CREATION=true
      - OAUTH_GROUP_CLAIM=groups
```

**Step 2: Update .env.example with required variables**

Create/update `.env.example`:

```bash
# Open WebUI Secret
WEBUI_SECRET_KEY=your-secret-key-here

# OpenAI
OPENAI_API_KEY=sk-...

# GitHub
GITHUB_TOKEN=ghp_...

# MCP API Key (internal)
MCP_API_KEY=test-key

# PostgreSQL
POSTGRES_PASSWORD=openwebui-secret

# Microsoft Entra ID
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_CLIENT_TENANT_ID=your-tenant-id

# Atlassian
ATLASSIAN_TOKEN=your-token

# Asana
ASANA_TOKEN=your-token
```

---

## Task 5: Complete docker-compose.yml Update

**Files:**
- Modify: `docker-compose.yml` (full file)

**Step 1: Write the complete updated docker-compose.yml**

See complete file below with all changes integrated.

**Step 2: Validate docker-compose syntax**

Run: `docker compose config`
Expected: Valid YAML output with all services

**Step 3: Pull all images**

Run: `docker compose pull`
Expected: All images pulled successfully

---

## Task 6: Test Full Stack Locally

**Step 1: Stop existing containers**

Run: `docker compose down`

**Step 2: Start new stack**

Run: `docker compose up -d`

**Step 3: Check all services are running**

Run: `docker compose ps`
Expected: All services healthy

**Step 4: Test Redis connectivity**

Run: `docker exec redis redis-cli ping`
Expected: `PONG`

**Step 5: Test PostgreSQL connectivity**

Run: `docker exec postgres pg_isready -U openwebui`
Expected: `accepting connections`

**Step 6: Test Open WebUI**

Run: `curl http://localhost:3000/health`
Expected: `200 OK`

**Step 7: Test MCP Proxy**

Run: `curl http://localhost:8000/health`
Expected: `200 OK`

---

## Complete Updated docker-compose.yml

```yaml
services:
  # ==========================================================================
  # Redis - Session & Cache Management
  # ==========================================================================
  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ==========================================================================
  # PostgreSQL + PGVector - Unified Database
  # ==========================================================================
  postgres:
    image: pgvector/pgvector:pg16
    container_name: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=openwebui
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-openwebui-secret}
      - POSTGRES_DB=openwebui
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U openwebui -d openwebui"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ==========================================================================
  # Ollama - Local LLM Server
  # ==========================================================================
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama
    restart: unless-stopped

  # ==========================================================================
  # Open WebUI v0.7 - Main Application
  # ==========================================================================
  open-webui:
    image: ghcr.io/open-webui/open-webui:v0.7.0
    container_name: open-webui
    ports:
      - "3000:8080"
    volumes:
      - open-webui-data:/app/backend/data
    environment:
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
      # Ollama connection (local LLMs)
      - OLLAMA_BASE_URL=http://ollama:11434
      # OpenAI connection (cloud LLMs)
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      # User headers for MCP Proxy
      - ENABLE_FORWARD_USER_INFO_HEADERS=true
      - BYPASS_MODEL_ACCESS_CONTROL=true
      # Redis for sessions and caching
      - REDIS_URL=redis://redis:6379/0
      - ENABLE_REDIS=true
      # PostgreSQL Database (replaces SQLite)
      - DATABASE_URL=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      # Vector Database (PGVector instead of ChromaDB)
      - VECTOR_DB=pgvector
      - PGVECTOR_CONNECTION_STRING=postgresql://openwebui:${POSTGRES_PASSWORD:-openwebui-secret}@postgres:5432/openwebui
      # Microsoft Entra ID OAuth
      - ENABLE_OAUTH_SIGNUP=true
      - OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
      - MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}
      - MICROSOFT_CLIENT_SECRET=${MICROSOFT_CLIENT_SECRET}
      - MICROSOFT_CLIENT_TENANT_ID=${MICROSOFT_CLIENT_TENANT_ID}
      # Group Management for Multi-Tenant
      - ENABLE_OAUTH_GROUP_MANAGEMENT=true
      - ENABLE_OAUTH_GROUP_CREATION=true
      - OAUTH_GROUP_CLAIM=groups
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      ollama:
        condition: service_started
    restart: unless-stopped

  # ==========================================================================
  # MCP Proxy Gateway - Multi-Tenant Tool Filtering
  # ==========================================================================
  mcp-proxy:
    build: ./mcp-proxy
    container_name: mcp-proxy
    ports:
      - "8000:8000"
    environment:
      - DEBUG=true
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
    restart: unless-stopped

  # ==========================================================================
  # MCP Filesystem Server - File Access Tools
  # ==========================================================================
  mcp-filesystem:
    image: node:20-slim
    container_name: mcp-filesystem
    command: >
      bash -c "apt-get update && apt-get install -y python3 python3-pip curl --no-install-recommends &&
               pip3 install --break-system-packages mcpo &&
               mcpo --host 0.0.0.0 --port 8001 --api-key test-key -- npx -y @modelcontextprotocol/server-filesystem /data"
    ports:
      - "8001:8001"
    volumes:
      - ./mcp-poc/test-data:/data
    restart: unless-stopped

  # ==========================================================================
  # MCP GitHub Server - GitHub API Tools
  # ==========================================================================
  mcp-github:
    build: ./mcp-servers/github
    container_name: mcp-github
    environment:
      - GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_TOKEN}
      - MCP_API_KEY=${MCP_API_KEY:-test-key}
    ports:
      - "8002:8000"
    restart: unless-stopped

  # ==========================================================================
  # TIER 2: SSE MCP Servers
  # ==========================================================================
  mcpo-sse-atlassian:
    image: ghcr.io/sooperset/mcp-atlassian:latest
    container_name: mcpo-sse-atlassian
    command: ["--transport", "streamable-http", "--port", "8010", "-vv"]
    ports:
      - "8010:8010"
    environment:
      - ATLASSIAN_OAUTH_ENABLE=true
      - ATLASSIAN_API_TOKEN=${ATLASSIAN_TOKEN}
    restart: unless-stopped

  mcpo-sse-asana:
    image: python:3.11-slim
    container_name: mcpo-sse-asana
    command: >
      bash -c "apt-get update && apt-get install -y curl nodejs npm --no-install-recommends &&
               pip install mcpo mcp-remote --quiet &&
               mcpo --host 0.0.0.0 --port 8011 --api-key ${MCP_API_KEY:-test-key} -- npx -y mcp-remote https://mcp.asana.com/sse"
    ports:
      - "8011:8011"
    environment:
      - MCP_API_KEY=${MCP_API_KEY:-test-key}
      - ASANA_TOKEN=${ASANA_TOKEN}
    restart: unless-stopped

  # ==========================================================================
  # TIER 3: STDIO MCP Servers
  # ==========================================================================
  mcpo-stdio-sonarqube:
    image: node:20-slim
    container_name: mcpo-stdio-sonarqube
    command: >
      bash -c "apt-get update && apt-get install -y python3 python3-pip --no-install-recommends &&
               pip3 install --break-system-packages mcpo &&
               mcpo --host 0.0.0.0 --port 8020 --api-key ${MCP_API_KEY:-test-key} -- npx -y @anthropic/mcp-sonarqube"
    ports:
      - "8020:8020"
    environment:
      - MCP_API_KEY=${MCP_API_KEY:-test-key}
      - SONARQUBE_URL=${SONARQUBE_URL}
      - SONARQUBE_TOKEN=${SONARQUBE_TOKEN}
    restart: unless-stopped

volumes:
  redis-data:
  postgres-data:
  ollama-data:
  open-webui-data:
```

---

## Open WebUI v0.7 New Features Summary

| Feature | Description | Impact |
|---------|-------------|--------|
| **Native Function Calling** | Multi-step tasks (web research + tools) | Better MCP integration |
| **Smart Router** | Auto-decides which tool to call | Improved UX |
| **Context Retrieval** | Query notes, chat history | Better memory |
| **Knowledge Base** | Auto-search without manual attachment | Easier docs |
| **Web Search Citations** | Clickable source links | Better trust |
| **Performance** | Reengineered DB connections | Faster |
| **Query Optimization** | 1+N → 2 queries | Scalable |

---

## Checklist

- [ ] Task 1: Update Open WebUI to v0.7
- [ ] Task 2: Add Redis service
- [ ] Task 3: Add PostgreSQL + PGVector
- [ ] Task 4: Configure Entra ID OAuth
- [ ] Task 5: Validate docker-compose
- [ ] Task 6: Test full stack locally
- [ ] Task 7: Deploy to Kubernetes (optional)

---

*Plan created: January 15, 2026*
