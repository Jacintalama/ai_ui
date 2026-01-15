# MCP Integration Architecture Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Date:** 2026-01-08
**Goal:** Comprehensive multi-tenant MCP integration with API Gateway, Entra ID authentication, and protocol bridging for 60+ third-party services.

**Architecture:** API Gateway validates Entra ID tokens, MCP Proxy routes by protocol tier, mcpo bridges SSE/stdio to HTTP.

**Tech Stack:** Kubernetes, Azure APIM, Entra ID, mcpo, PostgreSQL (row-level security with workspace_id)

---

## Section 1: Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT BROWSER                                   │
│                    (Microsoft Entra ID Token)                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (Azure APIM)                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ • Validate Entra ID Token                                       │    │
│  │ • Extract user identity (email, tenant, groups)                 │    │
│  │ • Rate limiting per tenant                                      │    │
│  │ • Route to appropriate backend                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Open WebUI     │    │   MCP Proxy      │    │   Direct HTTP    │
│   (Chat UI)      │    │   Gateway        │    │   MCP Servers    │
│   PostgreSQL     │    │   (Multi-tenant) │    │   (Tier 1)       │
│   workspace_id   │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   mcpo Proxy     │    │   mcpo Proxy     │    │   Self-hosted    │
│   (SSE servers)  │    │   (stdio)        │    │   MCP Servers    │
│   Tier 2         │    │   Tier 3         │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

**Key Concepts:**
- `workspace_id` in PostgreSQL = `tenant_id` = separation of concerns
- One database, row-level security (NOT 10 databases)
- API Gateway validates Entra ID, passes identity downstream

---

## Section 2: Kubernetes Service Architecture

All services run in the `open-webui` namespace (localhost:8080):

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    KUBERNETES CLUSTER (localhost:8080)                  │
│                         namespace: open-webui                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │  open-webui-0   │  │   postgresql    │  │     redis       │         │
│  │  (StatefulSet)  │  │  (Deployment)   │  │  (Deployment)   │         │
│  │  Port: 8080     │  │  Port: 5432     │  │  Port: 6379     │         │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘         │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    MCP PROXY GATEWAY                             │   │
│  │                    (Multi-Tenant Router)                         │   │
│  │                    Port: 8000                                    │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │  Routes by tier:                                         │    │   │
│  │  │  • Tier 1 (HTTP) → Direct to remote MCP servers          │    │   │
│  │  │  • Tier 2 (SSE)  → mcpo-sse service                      │    │   │
│  │  │  • Tier 3 (stdio)→ mcpo-stdio service                    │    │   │
│  │  └─────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │   mcpo-sse      │  │  mcpo-stdio     │  │  mcp-github     │         │
│  │  (Deployment)   │  │  (Deployment)   │  │  (Deployment)   │         │
│  │  Port: 8010+    │  │  Port: 8020+    │  │  Port: 8002     │         │
│  │  Atlassian,etc  │  │  SonarQube,etc  │  │  Already running│         │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘         │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐                              │
│  │ mcp-filesystem  │  │    pipelines    │                              │
│  │  (Deployment)   │  │  (Deployment)   │                              │
│  │  Port: 8001     │  │  Port: 9099     │                              │
│  │  Already running│  │  Already running│                              │
│  └─────────────────┘  └─────────────────┘                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Currently Running (7 pods):**
- open-webui-0, postgresql, redis, pipelines
- mcp-proxy, mcp-github, mcp-filesystem

**New Services to Add:**
| Service | Purpose | Handles |
|---------|---------|---------|
| `mcpo-sse` | Proxy for SSE servers | Atlassian, Asana, Slack |
| `mcpo-stdio` | Proxy for stdio servers | SonarQube, ClickUp, databases |

---

## Section 3: API Gateway + Entra ID Authentication

### Authentication Flow

```
1. User logs in via Microsoft Entra ID
   ┌──────────┐         ┌──────────────┐
   │  User    │ ──────► │  Entra ID    │
   │ Browser  │ ◄────── │  (Azure AD)  │
   └──────────┘  Token  └──────────────┘

2. Token contains user identity
   ┌─────────────────────────────────────────────────────────┐
   │  JWT Token Claims:                                       │
   │  {                                                       │
   │    "email": "john@contoso.com",                         │
   │    "oid": "user-object-id",                             │
   │    "tid": "tenant-id",           ← Azure tenant         │
   │    "groups": ["MCP-Google", "MCP-GitHub"],              │
   │    "roles": ["MCP.ReadWrite"]                           │
   │  }                                                       │
   └─────────────────────────────────────────────────────────┘

3. API Gateway validates & routes
   ┌──────────────────────────────────────────────────────────┐
   │  API Gateway (Azure APIM or Kong)                        │
   │  ┌────────────────────────────────────────────────────┐  │
   │  │  Policy:                                            │  │
   │  │  1. Validate JWT signature (Entra ID public key)    │  │
   │  │  2. Extract email, groups, tenant                   │  │
   │  │  3. Set headers:                                    │  │
   │  │     X-User-Email: john@contoso.com                  │  │
   │  │     X-User-Groups: MCP-Google,MCP-GitHub            │  │
   │  │     X-Tenant-ID: contoso                            │  │
   │  │  4. Forward to MCP Proxy Gateway                    │  │
   │  └────────────────────────────────────────────────────┘  │
   └──────────────────────────────────────────────────────────┘

4. MCP Proxy uses headers for access control
   ┌──────────────────────────────────────────────────────────┐
   │  MCP Proxy Gateway (mcp-proxy service)                   │
   │  ┌────────────────────────────────────────────────────┐  │
   │  │  # auth.py - Updated to read from API Gateway      │  │
   │  │  email = headers.get("X-User-Email")               │  │
   │  │  groups = headers.get("X-User-Groups").split(",")  │  │
   │  │                                                     │  │
   │  │  # Map Entra groups to tenants                     │  │
   │  │  # MCP-Google group → google tenant                │  │
   │  │  # MCP-GitHub group → github tenant                │  │
   │  └────────────────────────────────────────────────────┘  │
   └──────────────────────────────────────────────────────────┘
```

### Entra ID Group → Tenant Mapping

| Entra ID Group | MCP Tenant | Tools Access |
|----------------|------------|--------------|
| `MCP-Google` | google | Filesystem, Google Drive |
| `MCP-Microsoft` | microsoft | OneDrive, SharePoint, Teams |
| `MCP-GitHub` | github | GitHub (51 tools) |
| `MCP-Atlassian` | atlassian | Jira, Confluence |
| `MCP-Admin` | * (all) | All tenants |

**Key Change:** Instead of hardcoding users in `tenants.py`, read groups from Entra ID token via API Gateway headers.

---

## Section 4: MCP Proxy Routing by Protocol Tier

```
                         Incoming Request
                    (with X-User-Email, X-User-Groups)
                                │
                                ▼
                    ┌───────────────────────┐
                    │  1. Check user access │
                    │  2. Identify tool     │
                    │  3. Route by tier     │
                    └───────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│   TIER 1      │       │   TIER 2      │       │   TIER 3      │
│   HTTP        │       │   SSE         │       │   stdio       │
│   (Direct)    │       │   (mcpo-sse)  │       │   (mcpo-stdio)│
└───────────────┘       └───────────────┘       └───────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ Remote URLs:  │       │ K8s Service:  │       │ K8s Service:  │
│               │       │ mcpo-sse:8010 │       │ mcpo-stdio:   │
│ • Linear      │       │               │       │ 8020          │
│ • GitLab      │       │ Proxies to:   │       │               │
│ • Notion      │       │ • Atlassian   │       │ Runs locally: │
│ • GitHub      │       │ • Asana       │       │ • SonarQube   │
│ • HubSpot     │       │ • Slack       │       │ • ClickUp     │
│ • Snowflake   │       │               │       │ • PostgreSQL  │
│ • Pulumi      │       │               │       │ • Sentry      │
└───────────────┘       └───────────────┘       └───────────────┘
```

### Updated tenants.py Structure

```python
# Tier 1: Direct HTTP (no proxy needed)
TIER1_SERVERS = {
    "linear": {
        "url": "https://mcp.linear.app/mcp",
        "auth": "oauth2.1",
        "tenant": "linear"
    },
    "gitlab": {
        "url": "https://gitlab.com/api/v4/mcp",
        "auth": "oauth2.0",
        "tenant": "gitlab"
    },
    "github": {
        "url": "https://api.githubcopilot.com/mcp/",
        "auth": "oauth2.0",
        "tenant": "github"
    },
    # ... more Tier 1 servers
}

# Tier 2: SSE (route to mcpo-sse service)
TIER2_SERVERS = {
    "atlassian": {
        "proxy_url": "http://mcpo-sse:8010/atlassian",
        "remote_url": "https://mcp.atlassian.com/v1/sse",
        "tenant": "atlassian"
    },
    # ... more Tier 2 servers
}

# Tier 3: stdio (route to mcpo-stdio service)
TIER3_SERVERS = {
    "sonarqube": {
        "proxy_url": "http://mcpo-stdio:8020/sonarqube",
        "package": "@anthropic/mcp-sonarqube",
        "tenant": "sonarqube"
    },
    # ... more Tier 3 servers
}
```

---

## Section 5: mcpo Kubernetes Deployments

### mcpo-sse Deployment (Tier 2 servers)

```yaml
# kubernetes/mcpo-sse-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpo-sse
  namespace: open-webui
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcpo-sse
  template:
    spec:
      containers:
        # Atlassian proxy
        - name: atlassian
          image: python:3.11-slim
          command: ["uvx", "mcpo", "--port", "8010", "--server-type", "sse",
                    "--", "https://mcp.atlassian.com/v1/sse"]
          ports:
            - containerPort: 8010
          env:
            - name: ATLASSIAN_TOKEN
              valueFrom:
                secretKeyRef:
                  name: mcp-secrets
                  key: ATLASSIAN_TOKEN

        # Asana proxy
        - name: asana
          image: python:3.11-slim
          command: ["uvx", "mcpo", "--port", "8011", "--server-type", "sse",
                    "--", "https://mcp.asana.com/sse"]
          ports:
            - containerPort: 8011
---
apiVersion: v1
kind: Service
metadata:
  name: mcpo-sse
  namespace: open-webui
spec:
  ports:
    - name: atlassian
      port: 8010
    - name: asana
      port: 8011
  selector:
    app: mcpo-sse
```

### mcpo-stdio Deployment (Tier 3 servers)

```yaml
# kubernetes/mcpo-stdio-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpo-stdio
  namespace: open-webui
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcpo-stdio
  template:
    spec:
      containers:
        # SonarQube
        - name: sonarqube
          image: node:20-slim
          command: ["sh", "-c",
            "npm install -g mcpo @sonarqube/mcp-server &&
             mcpo --port 8020 -- npx @sonarqube/mcp-server"]
          ports:
            - containerPort: 8020
          env:
            - name: SONARQUBE_URL
              value: "https://sonar.company.com"
            - name: SONARQUBE_TOKEN
              valueFrom:
                secretKeyRef:
                  name: mcp-secrets
                  key: SONARQUBE_TOKEN

        # ClickUp
        - name: clickup
          image: node:20-slim
          command: ["sh", "-c",
            "npm install -g mcpo clickup-mcp-server &&
             mcpo --port 8021 -- npx clickup-mcp-server"]
          ports:
            - containerPort: 8021
          env:
            - name: CLICKUP_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-secrets
                  key: CLICKUP_API_KEY
---
apiVersion: v1
kind: Service
metadata:
  name: mcpo-stdio
  namespace: open-webui
spec:
  ports:
    - name: sonarqube
      port: 8020
    - name: clickup
      port: 8021
  selector:
    app: mcpo-stdio
```

### Port Summary

| Service | Port | Protocol | Servers |
|---------|------|----------|---------|
| mcpo-sse | 8010 | SSE→HTTP | Atlassian |
| mcpo-sse | 8011 | SSE→HTTP | Asana |
| mcpo-stdio | 8020 | stdio→HTTP | SonarQube |
| mcpo-stdio | 8021 | stdio→HTTP | ClickUp |

---

## Section 6: Implementation Priority (Quick Wins First)

### Phase 1: Quick Wins (This Week) - Tier 1 HTTP

No mcpo needed, just add to MCP Proxy config:

| Priority | Service | URL | Tools | Effort |
|----------|---------|-----|-------|--------|
| 1 | **Linear** | `https://mcp.linear.app/mcp` | Issues, projects | 30 min |
| 2 | **GitLab** | `https://gitlab.com/api/v4/mcp` | Repos, MRs, CI/CD | 30 min |
| 3 | **Notion** | `https://mcp.notion.com/mcp` | Pages, databases | 30 min |
| 4 | **GitHub** | `https://api.githubcopilot.com/mcp/` | 51 tools | Already done |
| 5 | **HubSpot** | `https://mcp.hubspot.com/anthropic` | CRM, contacts | 30 min |
| 6 | **Pulumi** | `https://mcp.ai.pulumi.com/mcp` | IaC, registry | 30 min |

### Phase 2: mcpo-sse (Next Week) - Tier 2 SSE

Deploy mcpo-sse pod, add servers:

| Priority | Service | Remote URL | Effort |
|----------|---------|------------|--------|
| 7 | **Atlassian** | `https://mcp.atlassian.com/v1/sse` | 2 hours |
| 8 | **Asana** | `https://mcp.asana.com/sse` | 1 hour |
| 9 | **Slack** | Wait for GA or community | TBD |

### Phase 3: mcpo-stdio (Week 3) - Tier 3 stdio

Deploy mcpo-stdio pod, add servers:

| Priority | Service | Package | Effort |
|----------|---------|---------|--------|
| 10 | **SonarQube** | `@sonarqube/mcp-server` | 2 hours |
| 11 | **Sentry** | Official MCP | 1 hour |
| 12 | **Datadog** | `shelfio/datadog-mcp` | 1 hour |
| 13 | **Google Drive** | `@modelcontextprotocol/gdrive` | 2 hours |
| 14 | **OneDrive/SharePoint** | `@microsoft/files-mcp-server` | 2 hours |

### Phase 4: API Gateway + Entra ID

| Task | Effort |
|------|--------|
| Set up Azure APIM or Kong | 4 hours |
| Configure Entra ID JWT validation | 2 hours |
| Update MCP Proxy to read headers | 2 hours |
| Create Entra ID groups (MCP-Google, etc.) | 1 hour |
| Migrate from hardcoded users → groups | 2 hours |

---

## Summary

| Component | Status | Location |
|-----------|--------|----------|
| Kubernetes Cluster | Running | localhost:8080 |
| Open WebUI + PostgreSQL | Running | 7 pods |
| MCP Proxy Gateway | Running | Multi-tenant routing |
| Tier 1 HTTP servers | Phase 1 | Direct connection |
| Tier 2 SSE servers | Phase 2 | mcpo-sse deployment |
| Tier 3 stdio servers | Phase 3 | mcpo-stdio deployment |
| API Gateway + Entra ID | Phase 4 | Azure APIM |

**Key Principles:**
- One PostgreSQL database with workspace_id = tenant (row-level security)
- API Gateway validates Entra ID, extracts groups
- MCP Proxy routes by protocol tier
- Quick wins first (Tier 1 HTTP), complexity later

---

## References

- MCP Integrations List: `C:\Users\alama\Desktop\Lukas Work\MCP-INTEGRATIONS.md`
- SSE vs Streaming Research: `docs/research/sse-vs-streaming-protocol.md`
- Community Pipelines: `docs/research/community-pipelines.md`
- Kubernetes Deployment: `docs/research/kubernetes-deployment.md`
