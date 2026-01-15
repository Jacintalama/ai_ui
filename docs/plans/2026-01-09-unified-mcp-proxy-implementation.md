# Unified MCP Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-01-09
**Author:** Jacint Alama
**Goal:** Deploy a unified MCP Proxy Gateway accessible to the entire team with hierarchical URL routing for all MCP integrations.

**Lukas's Requirement:**
> "One proxy server for all of them... the proxy's URL, slash github, slash linear, slash whatever else we deploy"

**Target URL Structure:**
```
https://mcp-proxy.company.com/github/search_repositories
https://mcp-proxy.company.com/linear/list_issues
https://mcp-proxy.company.com/atlassian/search_issues
```

**Deployment:** Azure Kubernetes Service (AKS)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              INTERNET                                        │
│                     (Team members access via browser/API)                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AZURE KUBERNETES SERVICE                             │
│                           namespace: open-webui                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    INGRESS CONTROLLER (NGINX)                          │ │
│  │                 https://mcp-proxy.company.com                          │ │
│  │                                                                         │ │
│  │  Routes:                                                                │ │
│  │    /github/*     ─┐                                                    │ │
│  │    /linear/*      │                                                    │ │
│  │    /notion/*      ├──► mcp-proxy Service (port 8000)                   │ │
│  │    /atlassian/*   │                                                    │ │
│  │    /filesystem/* ─┘                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                     MCP PROXY GATEWAY                                   │ │
│  │                     (Deployment: 2-5 replicas)                          │ │
│  │                                                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │  Routing Logic:                                                  │   │ │
│  │  │                                                                  │   │ │
│  │  │  /github/*     → TIER 1 (HTTP direct to GitHub API)             │   │ │
│  │  │  /linear/*     → TIER 1 (HTTP direct to Linear API)             │   │ │
│  │  │  /notion/*     → TIER 1 (HTTP direct to Notion API)             │   │ │
│  │  │  /hubspot/*    → TIER 1 (HTTP direct to HubSpot API)            │   │ │
│  │  │  /gitlab/*     → TIER 1 (HTTP direct to GitLab API)             │   │ │
│  │  │  /pulumi/*     → TIER 1 (HTTP direct to Pulumi API)             │   │ │
│  │  │                                                                  │   │ │
│  │  │  /atlassian/*  → TIER 2 (SSE via mcpo-sse:8010)                 │   │ │
│  │  │  /asana/*      → TIER 2 (SSE via mcpo-sse:8011)                 │   │ │
│  │  │                                                                  │   │ │
│  │  │  /sonarqube/*  → TIER 3 (stdio via mcpo-stdio:8020)             │   │ │
│  │  │  /sentry/*     → TIER 3 (stdio via mcpo-stdio:8021)             │   │ │
│  │  │                                                                  │   │ │
│  │  │  /filesystem/* → LOCAL (mcp-filesystem:8001)                    │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│          ┌─────────────────────────┼─────────────────────────┐              │
│          ▼                         ▼                         ▼              │
│  ┌───────────────┐        ┌───────────────┐        ┌───────────────┐       │
│  │  mcpo-sse     │        │  mcpo-stdio   │        │ mcp-filesystem│       │
│  │  (Tier 2)     │        │  (Tier 3)     │        │ mcp-github    │       │
│  │               │        │               │        │               │       │
│  │  :8010 Atlas  │        │  :8020 Sonar  │        │  :8001 Files  │       │
│  │  :8011 Asana  │        │  :8021 Sentry │        │  :8002 GitHub │       │
│  └───────────────┘        └───────────────┘        └───────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Task 1: Update MCP Proxy URL Routing

**Files to modify:**
- `mcp-proxy/main.py`
- `mcp-proxy/tenants.py`

### Step 1.1: Add Server Tier Configuration

Add to `mcp-proxy/tenants.py`:

```python
# =============================================================================
# MCP SERVER TIERS
# =============================================================================
# Tier 1: HTTP (direct connection, no proxy needed)
# Tier 2: SSE (requires mcpo-sse proxy)
# Tier 3: stdio (requires mcpo-stdio proxy)
# =============================================================================

from enum import Enum
from typing import Dict, Optional
import os

class ServerTier(Enum):
    HTTP = "http"      # Direct HTTP connection
    SSE = "sse"        # Requires mcpo SSE proxy
    STDIO = "stdio"    # Requires mcpo stdio proxy
    LOCAL = "local"    # Local container in cluster

@dataclass
class MCPServerConfig:
    """Configuration for an MCP server endpoint."""
    server_id: str
    display_name: str
    tier: ServerTier
    endpoint_url: str
    auth_type: str  # bearer, oauth, api_key
    api_key_env: Optional[str] = None
    enabled: bool = True

# Environment-based URLs for Kubernetes
MCPO_SSE_URL = os.getenv("MCPO_SSE_URL", "http://mcpo-sse")
MCPO_STDIO_URL = os.getenv("MCPO_STDIO_URL", "http://mcpo-stdio")
MCP_FILESYSTEM_URL = os.getenv("MCP_FILESYSTEM_URL", "http://mcp-filesystem:8001")
MCP_GITHUB_URL = os.getenv("MCP_GITHUB_URL", "http://mcp-github:8002")

# =============================================================================
# TIER 1: HTTP SERVERS (Direct Connection)
# =============================================================================
TIER1_SERVERS: Dict[str, MCPServerConfig] = {
    "github": MCPServerConfig(
        server_id="github",
        display_name="GitHub",
        tier=ServerTier.LOCAL,  # We have local container
        endpoint_url=MCP_GITHUB_URL,
        auth_type="bearer",
        api_key_env="GITHUB_TOKEN"
    ),
    "linear": MCPServerConfig(
        server_id="linear",
        display_name="Linear",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.linear.app/mcp",
        auth_type="oauth",
        api_key_env="LINEAR_API_KEY"
    ),
    "notion": MCPServerConfig(
        server_id="notion",
        display_name="Notion",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.notion.com/mcp",
        auth_type="bearer",
        api_key_env="NOTION_API_KEY"
    ),
    "hubspot": MCPServerConfig(
        server_id="hubspot",
        display_name="HubSpot",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.hubspot.com/anthropic",
        auth_type="bearer",
        api_key_env="HUBSPOT_API_KEY"
    ),
    "pulumi": MCPServerConfig(
        server_id="pulumi",
        display_name="Pulumi",
        tier=ServerTier.HTTP,
        endpoint_url="https://mcp.ai.pulumi.com/mcp",
        auth_type="bearer",
        api_key_env="PULUMI_ACCESS_TOKEN"
    ),
    "gitlab": MCPServerConfig(
        server_id="gitlab",
        display_name="GitLab",
        tier=ServerTier.HTTP,
        endpoint_url="https://gitlab.com/api/v4/mcp",
        auth_type="oauth",
        api_key_env="GITLAB_TOKEN"
    ),
}

# =============================================================================
# TIER 2: SSE SERVERS (via mcpo-sse proxy)
# =============================================================================
TIER2_SERVERS: Dict[str, MCPServerConfig] = {
    "atlassian": MCPServerConfig(
        server_id="atlassian",
        display_name="Atlassian (Jira/Confluence)",
        tier=ServerTier.SSE,
        endpoint_url=f"{MCPO_SSE_URL}:8010",
        auth_type="bearer",
        api_key_env="ATLASSIAN_TOKEN"
    ),
    "asana": MCPServerConfig(
        server_id="asana",
        display_name="Asana",
        tier=ServerTier.SSE,
        endpoint_url=f"{MCPO_SSE_URL}:8011",
        auth_type="bearer",
        api_key_env="ASANA_TOKEN"
    ),
}

# =============================================================================
# TIER 3: STDIO SERVERS (via mcpo-stdio proxy)
# =============================================================================
TIER3_SERVERS: Dict[str, MCPServerConfig] = {
    "sonarqube": MCPServerConfig(
        server_id="sonarqube",
        display_name="SonarQube",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8020",
        auth_type="bearer",
        api_key_env="SONARQUBE_TOKEN"
    ),
    "sentry": MCPServerConfig(
        server_id="sentry",
        display_name="Sentry",
        tier=ServerTier.STDIO,
        endpoint_url=f"{MCPO_STDIO_URL}:8021",
        auth_type="bearer",
        api_key_env="SENTRY_AUTH_TOKEN"
    ),
}

# =============================================================================
# LOCAL SERVERS (in-cluster containers)
# =============================================================================
LOCAL_SERVERS: Dict[str, MCPServerConfig] = {
    "filesystem": MCPServerConfig(
        server_id="filesystem",
        display_name="Filesystem",
        tier=ServerTier.LOCAL,
        endpoint_url=MCP_FILESYSTEM_URL,
        auth_type="api_key",
        api_key_env="MCP_API_KEY"
    ),
}

# Combined server registry
ALL_SERVERS: Dict[str, MCPServerConfig] = {
    **TIER1_SERVERS,
    **TIER2_SERVERS,
    **TIER3_SERVERS,
    **LOCAL_SERVERS,
}

def get_server(server_id: str) -> Optional[MCPServerConfig]:
    """Get server configuration by ID."""
    return ALL_SERVERS.get(server_id)

def get_all_servers() -> Dict[str, MCPServerConfig]:
    """Get all configured servers."""
    return ALL_SERVERS
```

### Step 1.2: Update Main Routing Logic

Replace routing in `mcp-proxy/main.py`:

```python
# =============================================================================
# HIERARCHICAL ROUTING: /{server}/{tool}
# =============================================================================

from tenants import get_server, get_all_servers, ALL_SERVERS, ServerTier

@app.get("/")
async def list_servers():
    """List all available MCP servers."""
    servers = []
    for server_id, config in ALL_SERVERS.items():
        servers.append({
            "id": server_id,
            "name": config.display_name,
            "tier": config.tier.value,
            "enabled": config.enabled,
            "endpoint": f"/{server_id}/"
        })
    return {"servers": servers}


@app.get("/{server_id}")
async def get_server_info(server_id: str):
    """Get information about a specific server."""
    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    # Fetch tools from this server
    tools = await fetch_server_tools(server)

    return {
        "server": server_id,
        "name": server.display_name,
        "tier": server.tier.value,
        "tools": tools
    }


@app.post("/{server_id}/{tool_path:path}")
async def execute_server_tool(server_id: str, tool_path: str, request: Request):
    """
    Execute a tool on a specific server.

    Examples:
        POST /github/search_repositories
        POST /linear/list_issues
        POST /atlassian/search_issues
    """
    # Get server config
    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    if not server.enabled:
        raise HTTPException(status_code=503, detail=f"Server '{server_id}' is disabled")

    # Check user access (if headers present)
    user = extract_user_from_headers_optional(request)
    if user:
        if not user_has_server_access(user.email, server_id):
            raise HTTPException(
                status_code=403,
                detail=f"User {user.email} does not have access to server '{server_id}'"
            )

    # Parse request body
    try:
        body = await request.json()
    except:
        body = {}

    # Route based on tier
    if server.tier == ServerTier.HTTP:
        return await execute_http_tool(server, tool_path, body)
    elif server.tier == ServerTier.SSE:
        return await execute_via_mcpo(server, tool_path, body)
    elif server.tier == ServerTier.STDIO:
        return await execute_via_mcpo(server, tool_path, body)
    elif server.tier == ServerTier.LOCAL:
        return await execute_local_tool(server, tool_path, body)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown tier: {server.tier}")


async def execute_http_tool(server: MCPServerConfig, tool_path: str, body: dict):
    """Execute tool on HTTP-based MCP server (Tier 1)."""
    api_key = os.getenv(server.api_key_env, "")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{server.endpoint_url}/{tool_path}",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )


async def execute_via_mcpo(server: MCPServerConfig, tool_path: str, body: dict):
    """Execute tool via mcpo proxy (Tier 2 SSE or Tier 3 stdio)."""
    api_key = os.getenv(server.api_key_env, "")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{server.endpoint_url}/{tool_path}",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )


async def execute_local_tool(server: MCPServerConfig, tool_path: str, body: dict):
    """Execute tool on local in-cluster MCP server."""
    api_key = os.getenv(server.api_key_env, "test-key")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{server.endpoint_url}/{tool_path}",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )
```

### Step 1.3: Commit Changes

```bash
git add mcp-proxy/main.py mcp-proxy/tenants.py
git commit -m "feat: add hierarchical URL routing for unified MCP proxy

- Add /{server}/{tool} URL pattern
- Configure Tier 1/2/3 server routing
- Add server discovery endpoints"
```

---

## Task 2: Add mcpo Containers for Tier 2/3

**Files to create/modify:**
- `docker-compose.yml`
- `kubernetes/mcpo-sse-deployment.yaml`
- `kubernetes/mcpo-stdio-deployment.yaml`

### Step 2.1: Update docker-compose.yml

Add to `docker-compose.yml`:

```yaml
  # ==========================================================================
  # mcpo SSE Proxy - Converts SSE to HTTP (Tier 2)
  # ==========================================================================
  mcpo-sse-atlassian:
    image: python:3.11-slim
    container_name: mcpo-sse-atlassian
    command: >
      bash -c "pip install mcpo uvicorn &&
               mcpo --host 0.0.0.0 --port 8010 --api-key ${MCP_API_KEY:-test-key}
               --server-type sse -- https://mcp.atlassian.com/v1/sse"
    ports:
      - "8010:8010"
    environment:
      - ATLASSIAN_TOKEN=${ATLASSIAN_TOKEN}
    restart: unless-stopped

  mcpo-sse-asana:
    image: python:3.11-slim
    container_name: mcpo-sse-asana
    command: >
      bash -c "pip install mcpo uvicorn &&
               mcpo --host 0.0.0.0 --port 8011 --api-key ${MCP_API_KEY:-test-key}
               --server-type sse -- https://mcp.asana.com/sse"
    ports:
      - "8011:8011"
    environment:
      - ASANA_TOKEN=${ASANA_TOKEN}
    restart: unless-stopped

  # ==========================================================================
  # mcpo stdio Proxy - Converts stdio to HTTP (Tier 3)
  # ==========================================================================
  mcpo-stdio-sonarqube:
    image: node:20-slim
    container_name: mcpo-stdio-sonarqube
    command: >
      bash -c "apt-get update && apt-get install -y python3 python3-pip --no-install-recommends &&
               pip3 install --break-system-packages mcpo &&
               npm install -g @sonarqube/mcp-server &&
               mcpo --host 0.0.0.0 --port 8020 --api-key ${MCP_API_KEY:-test-key}
               -- npx @sonarqube/mcp-server"
    ports:
      - "8020:8020"
    environment:
      - SONARQUBE_URL=${SONARQUBE_URL}
      - SONARQUBE_TOKEN=${SONARQUBE_TOKEN}
    restart: unless-stopped
```

### Step 2.2: Update .env Template

Add to `.env.example`:

```bash
# =============================================================================
# TIER 1: HTTP MCP SERVERS
# =============================================================================
LINEAR_API_KEY=your-linear-api-key
NOTION_API_KEY=your-notion-integration-token
HUBSPOT_API_KEY=your-hubspot-api-key
PULUMI_ACCESS_TOKEN=your-pulumi-token
GITLAB_TOKEN=your-gitlab-personal-access-token

# =============================================================================
# TIER 2: SSE MCP SERVERS (via mcpo)
# =============================================================================
ATLASSIAN_TOKEN=your-atlassian-api-token
ASANA_TOKEN=your-asana-personal-access-token

# =============================================================================
# TIER 3: STDIO MCP SERVERS (via mcpo)
# =============================================================================
SONARQUBE_URL=https://sonar.company.com
SONARQUBE_TOKEN=your-sonarqube-token
SENTRY_AUTH_TOKEN=your-sentry-auth-token
```

### Step 2.3: Commit Changes

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add mcpo containers for Tier 2 (SSE) and Tier 3 (stdio) servers"
```

---

## Task 3: Create Kubernetes Secrets

**Files to create:**
- `kubernetes/mcp-secrets.yaml`

### Step 3.1: Create Secrets Template

```yaml
# kubernetes/mcp-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-api-keys
  namespace: open-webui
type: Opaque
stringData:
  # Tier 1: HTTP
  GITHUB_TOKEN: "ghp_your_github_token"
  LINEAR_API_KEY: "lin_api_your_key"
  NOTION_API_KEY: "secret_your_notion_key"
  HUBSPOT_API_KEY: "your_hubspot_key"
  PULUMI_ACCESS_TOKEN: "pul_your_token"
  GITLAB_TOKEN: "glpat_your_token"

  # Tier 2: SSE
  ATLASSIAN_TOKEN: "your_atlassian_token"
  ASANA_TOKEN: "your_asana_token"

  # Tier 3: stdio
  SONARQUBE_URL: "https://sonar.company.com"
  SONARQUBE_TOKEN: "your_sonar_token"
  SENTRY_AUTH_TOKEN: "your_sentry_token"

  # Internal
  MCP_API_KEY: "internal-mcp-key"
```

### Step 3.2: Commit (template only, not real secrets)

```bash
git add kubernetes/mcp-secrets.yaml
git commit -m "feat: add Kubernetes secrets template for MCP API keys"
```

---

## Task 4: Update Kubernetes Deployments

**Files to modify:**
- `kubernetes/mcp-proxy-deployment.yaml`
- `kubernetes/mcpo-sse-deployment.yaml`
- `kubernetes/mcpo-stdio-deployment.yaml`

### Step 4.1: Update MCP Proxy Deployment

Update `kubernetes/mcp-proxy-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-proxy
  namespace: open-webui
  labels:
    app: mcp-proxy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-proxy
  template:
    metadata:
      labels:
        app: mcp-proxy
    spec:
      containers:
        - name: mcp-proxy
          image: your-registry/mcp-proxy:latest
          ports:
            - containerPort: 8000
          env:
            # Internal service URLs
            - name: MCP_FILESYSTEM_URL
              value: "http://mcp-filesystem:8001"
            - name: MCP_GITHUB_URL
              value: "http://mcp-github:8002"
            - name: MCPO_SSE_URL
              value: "http://mcpo-sse"
            - name: MCPO_STDIO_URL
              value: "http://mcpo-stdio"
            # API Keys from secrets
            - name: GITHUB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: GITHUB_TOKEN
            - name: LINEAR_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: LINEAR_API_KEY
            - name: NOTION_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: NOTION_API_KEY
            - name: HUBSPOT_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: HUBSPOT_API_KEY
            - name: ATLASSIAN_TOKEN
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: ATLASSIAN_TOKEN
            - name: ASANA_TOKEN
              valueFrom:
                secretKeyRef:
                  name: mcp-api-keys
                  key: ASANA_TOKEN
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 20
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-proxy
  namespace: open-webui
spec:
  selector:
    app: mcp-proxy
  ports:
    - port: 8000
      targetPort: 8000
  type: ClusterIP
```

### Step 4.2: Create Ingress for External Access

Create `kubernetes/mcp-proxy-ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-proxy-ingress
  namespace: open-webui
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
spec:
  tls:
    - hosts:
        - mcp-proxy.company.com
      secretName: mcp-proxy-tls
  rules:
    - host: mcp-proxy.company.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mcp-proxy
                port:
                  number: 8000
```

### Step 4.3: Commit Changes

```bash
git add kubernetes/mcp-proxy-deployment.yaml kubernetes/mcp-proxy-ingress.yaml
git commit -m "feat: add Kubernetes ingress for unified MCP proxy external access"
```

---

## Task 5: Deploy to Azure Kubernetes

### Step 5.1: Prerequisites

```bash
# 1. Login to Azure
az login

# 2. Set subscription
az account set --subscription "your-subscription-id"

# 3. Get AKS credentials
az aks get-credentials --resource-group your-rg --name your-aks-cluster

# 4. Verify connection
kubectl get nodes
```

### Step 5.2: Create Namespace and Secrets

```bash
# Create namespace
kubectl apply -f kubernetes/namespace.yaml

# Create secrets (edit with real values first!)
kubectl apply -f kubernetes/mcp-secrets.yaml
```

### Step 5.3: Deploy MCP Proxy

```bash
# Deploy MCP Proxy
kubectl apply -f kubernetes/mcp-proxy-deployment.yaml

# Deploy mcpo proxies
kubectl apply -f kubernetes/mcpo-sse-deployment.yaml
kubectl apply -f kubernetes/mcpo-stdio-deployment.yaml

# Deploy filesystem and github servers
kubectl apply -f kubernetes/mcp-filesystem-deployment.yaml
kubectl apply -f kubernetes/mcp-github-deployment.yaml

# Create ingress for external access
kubectl apply -f kubernetes/mcp-proxy-ingress.yaml
```

### Step 5.4: Verify Deployment

```bash
# Check pods
kubectl get pods -n open-webui

# Check services
kubectl get svc -n open-webui

# Check ingress
kubectl get ingress -n open-webui

# Test health endpoint
curl https://mcp-proxy.company.com/health
```

### Step 5.5: Share URL with Team

Once deployed, share with team:

```
MCP Proxy URL: https://mcp-proxy.company.com

Available Endpoints:
  /                     - List all servers
  /github/              - GitHub tools
  /linear/              - Linear tools
  /notion/              - Notion tools
  /atlassian/           - Atlassian/Jira tools
  /filesystem/          - File access tools
  /health               - Health check
```

---

## Task 6: Update Open WebUI Configuration

### Step 6.1: Add Unified Proxy to Open WebUI

In Open WebUI Admin Panel:

1. Go to **Settings → External Tools**
2. Add new tool server:
   - **Name:** `MCP Unified Proxy`
   - **URL:** `https://mcp-proxy.company.com`
   - **API Key:** `your-internal-mcp-key`
3. Click **Verify Connection**
4. Click **Save**

### Step 6.2: Enable Tools for Models

1. Go to **Settings → Models**
2. Select model (e.g., `gpt-4`)
3. In **Tools** section, enable `MCP Unified Proxy`
4. Click **Save & Update**

---

## Summary: Final URL Structure

After deployment, the team can access:

```
https://mcp-proxy.company.com/
│
├── /                           # List all available servers
├── /health                     # Health check
│
├── /github/                    # GitHub MCP (Tier 1 - HTTP)
│   ├── /github/search_repositories
│   ├── /github/list_repos
│   ├── /github/create_issue
│   └── /github/...
│
├── /linear/                    # Linear MCP (Tier 1 - HTTP)
│   ├── /linear/list_issues
│   ├── /linear/create_issue
│   └── /linear/...
│
├── /notion/                    # Notion MCP (Tier 1 - HTTP)
│   ├── /notion/search_pages
│   ├── /notion/get_page
│   └── /notion/...
│
├── /atlassian/                 # Atlassian MCP (Tier 2 - SSE via mcpo)
│   ├── /atlassian/search_issues
│   ├── /atlassian/create_issue
│   └── /atlassian/...
│
├── /asana/                     # Asana MCP (Tier 2 - SSE via mcpo)
│   ├── /asana/list_tasks
│   ├── /asana/create_task
│   └── /asana/...
│
├── /sonarqube/                 # SonarQube MCP (Tier 3 - stdio via mcpo)
│   ├── /sonarqube/analyze
│   └── /sonarqube/...
│
└── /filesystem/                # Filesystem MCP (Local)
    ├── /filesystem/read_file
    ├── /filesystem/list_directory
    └── /filesystem/...
```

---

## Checklist

| # | Task | Status |
|---|------|--------|
| 1 | Update `tenants.py` with server tiers | Pending |
| 2 | Update `main.py` with hierarchical routing | Pending |
| 3 | Add mcpo containers to docker-compose | Pending |
| 4 | Create Kubernetes secrets | Pending |
| 5 | Update Kubernetes deployments | Pending |
| 6 | Create ingress for external access | Pending |
| 7 | Deploy to AKS | Pending |
| 8 | Configure Open WebUI | Pending |
| 9 | Share URL with team | Pending |
| 10 | Document for Clarenz's spreadsheet | Pending |

---

## Team Responsibilities

| Person | Task |
|--------|------|
| **Jacint** | Implement routing changes, deploy to Kubernetes |
| **Jumar** | Test Tier 1 servers (Linear, Notion), document API keys |
| **Clarenz** | Update shared spreadsheet with new URLs and endpoints |
| **Lukas** | Review and approve deployment, provide API keys |

---

## References

- Current MCP Proxy: `mcp-proxy/main.py`
- Kubernetes manifests: `kubernetes/`
- Architecture doc: `docs/plans/2026-01-08-mcp-integration-architecture-design.md`
- Verification report: `docs/verification-report-2026-01-08.md`
