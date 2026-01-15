# Client Requirements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement client's requirements including MCP integrations, protocol bridging, community pipelines, and Kubernetes deployment preparation.

**Architecture:** Multi-phase approach starting with simple MCP testing (GitHub), then protocol research for Atlassian, community pipeline exploration, and finally Kubernetes deployment using official Helm charts.

**Tech Stack:** Python, FastAPI, Docker, Kubernetes, Helm, Open WebUI, MCP Protocol

---

## Understanding Criteria (From Client Notes)

### What Client Wants

| Priority | Requirement | Status |
|----------|-------------|--------|
| 1 | MCP Server familiarity (test with GitHub) | Pending |
| 2 | Multi-tenant tool isolation | ✅ Done (MCP Proxy Gateway) |
| 3 | User permissions | ✅ Done |
| 4 | SSE to Streaming protocol bridge (Atlassian/Jira) | Research needed |
| 5 | Community pipelines (N8N, Anthropic) | Research needed |
| 6 | Kubernetes deployment with official Helm charts | Pending |
| 7 | Documentation of integration learnings | Pending |

### Client's Key Problems

1. **Protocol Mismatch:** Atlassian MCP uses SSE, Open WebUI uses Streaming - they don't communicate
2. **Kubernetes Disaster:** Infrastructure guy built wrong solution (10 databases, custom infra)
3. **Need Familiarity:** Team needs hands-on experience with MCP servers

### Client's Recommendations

- Use existing community tools, don't reinvent
- Test with personal tools (GitHub, Trello, Todoist)
- Use official OpenWebUI Helm charts
- Document all integration challenges

---

## Phase 1: GitHub MCP Integration Testing

### Task 1.1: Research GitHub MCP Server

**Files:**
- Create: `docs/research/github-mcp-research.md`

**Step 1: Search for GitHub MCP server**

Research the official GitHub MCP server:
- Repository: https://github.com/modelcontextprotocol/servers
- Look for `github` server in the list

**Step 2: Document findings**

Create research document with:
- Installation requirements
- Configuration options
- Available tools/functions
- Protocol type (SSE vs Streaming)

**Step 3: Commit**

```bash
git add docs/research/github-mcp-research.md
git commit -m "docs: add GitHub MCP server research"
```

### Task 1.2: Install GitHub MCP Server

**Files:**
- Modify: `docker-compose.yml`
- Create: `mcp-servers/github/Dockerfile`

**Step 1: Create GitHub MCP server configuration**

```yaml
# Add to docker-compose.yml
services:
  mcp-github:
    build: ./mcp-servers/github
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    ports:
      - "8002:8000"
```

**Step 2: Create Dockerfile for GitHub MCP**

```dockerfile
FROM python:3.11-slim
RUN pip install mcp-server-github
CMD ["python", "-m", "mcp_server_github"]
```

**Step 3: Test connection**

```bash
docker compose up -d mcp-github
curl http://localhost:8002/health
```

**Step 4: Commit**

```bash
git add docker-compose.yml mcp-servers/github/
git commit -m "feat: add GitHub MCP server configuration"
```

### Task 1.3: Connect GitHub MCP to Open WebUI

**Files:**
- Modify: Open WebUI Admin Settings

**Step 1: Add MCP connection in Open WebUI**

1. Go to Admin Panel → Settings → MCP Servers
2. Add new server:
   - Name: `GitHub`
   - URL: `http://host.docker.internal:8002`
   - API Key: (if required)

**Step 2: Test GitHub tools**

1. Start a new chat
2. Check if GitHub tools appear
3. Test a simple query: "List my GitHub repositories"

**Step 3: Document results**

Record what works and what doesn't in `docs/research/github-mcp-research.md`

---

## Phase 2: SSE to Streaming Protocol Bridge Research

### Task 2.1: Understand the Protocol Problem

**Files:**
- Create: `docs/research/sse-vs-streaming-protocol.md`

**Step 1: Research SSE Protocol**

Server-Sent Events (SSE):
- One-way communication (server → client)
- Uses `text/event-stream` content type
- Atlassian/Jira MCP uses this

**Step 2: Research Streaming Protocol**

MCP Streaming (stdio):
- Bidirectional communication
- Uses JSON-RPC over stdio
- Open WebUI expects this

**Step 3: Document the mismatch**

```markdown
## Why Atlassian MCP Doesn't Work with Open WebUI

| Aspect | Atlassian MCP | Open WebUI Expected |
|--------|---------------|---------------------|
| Protocol | SSE (Server-Sent Events) | Streaming (stdio) |
| Communication | One-way | Bidirectional |
| Transport | HTTP | stdio/subprocess |

**Result:** They cannot communicate directly.
```

**Step 4: Commit**

```bash
git add docs/research/sse-vs-streaming-protocol.md
git commit -m "docs: document SSE vs Streaming protocol mismatch"
```

### Task 2.2: Research Protocol Bridge Solutions

**Files:**
- Modify: `docs/research/sse-vs-streaming-protocol.md`

**Step 1: Research existing solutions**

Look for:
- mcpo (MCP-over-HTTP proxy) - converts stdio to HTTP
- SSE-to-stdio bridges
- Community solutions

**Step 2: Research mcpo proxy**

mcpo converts MCP servers from stdio to HTTP:
```bash
pip install mcpo
mcpo --port 8001 -- npx @anthropic/mcp-server-atlassian
```

**Step 3: Document potential solutions**

```markdown
## Potential Solutions

### Option A: Use mcpo proxy (Recommended)
- mcpo converts stdio MCP to HTTP
- Open WebUI can connect to HTTP endpoints
- Requires wrapping Atlassian MCP with mcpo

### Option B: Custom SSE-to-Streaming adapter
- Build Python adapter that:
  1. Receives SSE from Atlassian
  2. Converts to MCP streaming format
  3. Sends to Open WebUI
- More complex, more control

### Option C: Wait for Open WebUI SSE support
- Open WebUI may add SSE support in future
- Not actionable now
```

**Step 4: Commit**

```bash
git add docs/research/sse-vs-streaming-protocol.md
git commit -m "docs: add protocol bridge solutions research"
```

### Task 2.3: Prototype SSE Bridge (If Needed)

**Files:**
- Create: `mcp-proxy/sse_bridge.py`

**Step 1: Create basic SSE bridge skeleton**

```python
# mcp-proxy/sse_bridge.py
"""
SSE to Streaming Protocol Bridge

Converts SSE (Server-Sent Events) from Atlassian MCP
to Streaming format expected by Open WebUI.
"""

import asyncio
import aiohttp
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="SSE to Streaming Bridge")

class SSEBridge:
    def __init__(self, sse_url: str):
        self.sse_url = sse_url

    async def convert_sse_to_stream(self):
        """Convert SSE events to streaming format."""
        async with aiohttp.ClientSession() as session:
            async with session.get(self.sse_url) as response:
                async for line in response.content:
                    if line.startswith(b'data:'):
                        yield self.convert_to_mcp_format(line)

    def convert_to_mcp_format(self, sse_data: bytes) -> bytes:
        """Convert SSE data to MCP streaming format."""
        # Implementation depends on specific MCP format
        pass

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "sse-bridge"}
```

**Step 2: Test with mock SSE server**

```bash
# This is a research prototype, not production code
python -m uvicorn mcp-proxy.sse_bridge:app --port 8003
```

**Step 3: Commit**

```bash
git add mcp-proxy/sse_bridge.py
git commit -m "feat: add SSE bridge prototype (research)"
```

---

## Phase 3: Community Pipelines Exploration

### Task 3.1: Research N8N Pipeline

**Files:**
- Create: `docs/research/community-pipelines.md`

**Step 1: Find N8N pipeline on Open WebUI community**

1. Go to https://openwebui.com/search?type=function
2. Search for "N8N"
3. Document installation and usage

**Step 2: Document N8N pipeline**

```markdown
## N8N Pipeline

**Source:** [link from community]

**Purpose:** Trigger N8N workflows from Open WebUI chat

**Installation:**
1. Go to Admin Panel → Functions
2. Import from community or paste code

**Usage:**
- Connect to N8N webhook
- Trigger workflows from chat commands
```

**Step 3: Commit**

```bash
git add docs/research/community-pipelines.md
git commit -m "docs: add N8N pipeline research"
```

### Task 3.2: Research Anthropic Pipeline

**Files:**
- Modify: `docs/research/community-pipelines.md`

**Step 1: Find Anthropic pipeline**

1. Search community for "Anthropic" or "Claude"
2. Look for Opus/Sonnet model integration

**Step 2: Document Anthropic pipeline**

```markdown
## Anthropic Pipeline (Claude Models)

**Source:** [link from community]

**Purpose:** Use Claude Opus/Sonnet models in Open WebUI

**Requirements:**
- Anthropic API key
- Pipeline installation

**Models Available:**
- claude-3-opus
- claude-3-sonnet
- claude-3-haiku
```

**Step 3: Commit**

```bash
git add docs/research/community-pipelines.md
git commit -m "docs: add Anthropic pipeline research"
```

---

## Phase 4: Documentation of Integration Learnings

### Task 4.1: Create Integration Guide

**Files:**
- Create: `docs/integration-guide.md`

**Step 1: Create comprehensive integration guide**

```markdown
# Open WebUI Integration Guide

## MCP Server Integration

### What Works
- GitHub MCP (streaming protocol)
- Custom MCP Proxy Gateway (our implementation)

### What Doesn't Work (and Why)
- Atlassian/Jira MCP: Uses SSE protocol, Open WebUI expects streaming
- Solution: Use mcpo proxy or build SSE bridge

### Protocol Reference

| MCP Server | Protocol | Open WebUI Compatible |
|------------|----------|----------------------|
| GitHub | Streaming | Yes |
| Atlassian | SSE | No (needs bridge) |
| Custom (ours) | HTTP | Yes (via mcpo) |

## Multi-Tenant Architecture

### Our Solution: MCP Proxy Gateway
- Filters tools by user's tenant access
- Injects tenant-specific credentials
- See `mcp-proxy/` directory

### How It Works
1. User makes request with X-User-Email header
2. Proxy checks user's tenant access
3. Returns only authorized tools
4. Injects correct credentials for tool execution

## Community Pipelines

### Recommended
- N8N Pipeline: Workflow automation
- Anthropic Pipeline: Claude models

### Where to Find
- https://openwebui.com/search?type=function
```

**Step 2: Commit**

```bash
git add docs/integration-guide.md
git commit -m "docs: add comprehensive integration guide"
```

---

## Phase 5: Kubernetes Deployment Preparation

### Task 5.1: Research Official Helm Charts

**Files:**
- Create: `docs/research/kubernetes-deployment.md`

**Step 1: Find official Helm charts**

Repository: https://github.com/open-webui/open-webui
Look in `/kubernetes` or `/helm` directory

**Step 2: Document Helm chart usage**

```markdown
# Kubernetes Deployment Guide

## Official Helm Charts

**DO NOT use custom infrastructure!**

The client's infrastructure guy made:
- 10 separate databases (wrong)
- Custom Kubernetes setup (doesn't work)

**USE the official OpenWebUI Helm charts instead.**

## Installation

```bash
# Add Helm repo
helm repo add open-webui https://helm.openwebui.com
helm repo update

# Install
helm install open-webui open-webui/open-webui \
  --namespace open-webui \
  --create-namespace \
  --set persistence.enabled=true \
  --set ingress.enabled=true
```

## Key Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| Database | Single PostgreSQL | NOT 10 databases! |
| Replicas | 3+ for 15k users | Scale based on load |
| Persistence | Enabled | For data retention |
```

**Step 3: Commit**

```bash
git add docs/research/kubernetes-deployment.md
git commit -m "docs: add Kubernetes deployment guide with official Helm charts"
```

### Task 5.2: Create Helm Values for Our Setup

**Files:**
- Create: `kubernetes/values.yaml`

**Step 1: Create custom values file**

```yaml
# kubernetes/values.yaml
# Custom values for Open WebUI Helm chart

replicaCount: 3

image:
  repository: ghcr.io/open-webui/open-webui
  tag: main
  pullPolicy: Always

service:
  type: ClusterIP
  port: 8080

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: openwebui.company.com
      paths:
        - path: /
          pathType: Prefix

persistence:
  enabled: true
  size: 50Gi
  storageClass: standard

postgresql:
  enabled: true
  auth:
    database: openwebui
    username: openwebui
  primary:
    persistence:
      enabled: true
      size: 20Gi

env:
  - name: BYPASS_MODEL_ACCESS_CONTROL
    value: "true"
  - name: ENABLE_FORWARD_USER_INFO_HEADERS
    value: "true"

# MCP Proxy sidecar (our multi-tenant gateway)
extraContainers:
  - name: mcp-proxy
    image: company/mcp-proxy:latest
    ports:
      - containerPort: 8080
```

**Step 2: Commit**

```bash
git add kubernetes/values.yaml
git commit -m "feat: add custom Helm values for Kubernetes deployment"
```

---

## Summary: Client Requirements Checklist

| # | Requirement | Phase | Status |
|---|-------------|-------|--------|
| 1 | MCP Server familiarity (GitHub) | Phase 1 | Pending |
| 2 | Multi-tenant tool isolation | Already Done | ✅ Complete |
| 3 | User permissions | Already Done | ✅ Complete |
| 4 | SSE to Streaming bridge research | Phase 2 | Pending |
| 5 | Community pipelines (N8N, Anthropic) | Phase 3 | Pending |
| 6 | Documentation of learnings | Phase 4 | Pending |
| 7 | Kubernetes with official Helm charts | Phase 5 | Pending |

---

## Execution Order

1. **Phase 1** (Quick Win): Test GitHub MCP - builds familiarity
2. **Phase 2** (Research): SSE protocol bridge - solves Atlassian problem
3. **Phase 3** (Explore): Community pipelines - adds capabilities
4. **Phase 4** (Document): Integration guide - helps team
5. **Phase 5** (Deploy): Kubernetes - production readiness
