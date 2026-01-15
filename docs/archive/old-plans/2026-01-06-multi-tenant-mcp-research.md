# Multi-Tenant MCP Integration Research & Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Research and document architecture options for multi-tenant MCP server integration in Open WebUI for a 15,000-employee company with isolated client data (Google, Microsoft, etc.).

**Architecture:** Multi-tenant Open WebUI deployment where each tenant (client) has isolated access to their own MCP tools/APIs (Jira, Atlassian, etc.) with per-user credential management and cross-tenant access for internal employees.

**Tech Stack:** Open WebUI, MCP (Model Context Protocol), mcpo proxy, OAuth 2.1, API Gateway (Kong/custom), Kubernetes

---

## Executive Summary

### The Core Problem

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         COMPANY GPT (Open WebUI)                        │
│                           15,000 employees                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  TENANT: Google        TENANT: Microsoft      TENANT: Company C         │
│  ┌─────────────┐       ┌─────────────┐        ┌─────────────┐          │
│  │ Google Jira │       │ MS Jira     │        │ C's Jira    │          │
│  │ Google APIs │       │ MS APIs     │        │ C's APIs    │          │
│  │ API Key: G1 │       │ API Key: M1 │        │ API Key: C1 │          │
│  └─────────────┘       └─────────────┘        └─────────────┘          │
│        ↑                     ↑                      ↑                   │
│   Google employees      MS employees           C employees              │
│   ONLY see Google       ONLY see MS            ONLY see C               │
│                                                                         │
│  INTERNAL EMPLOYEES (can span multiple tenants):                        │
│  - Employee A: Access to Google + Microsoft                             │
│  - Employee B: Access to Microsoft only                                 │
│  - Employee C: Access to all three                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Challenges

1. **Per-Tenant API Credentials** - Each client has their own Jira/Atlassian API keys
2. **User-Tenant Mapping** - Internal employees may work across multiple clients
3. **Data Isolation** - Google data must never leak to Microsoft users
4. **MCP Tool Isolation** - MCP servers expose tools globally; need per-tenant filtering
5. **Scalability** - Must handle 15,000+ concurrent users on Kubernetes

---

## Research Findings

### 1. Open WebUI MCP Support (v0.6.31+)

**Source:** [MCP Support | Open WebUI](https://docs.openwebui.com/features/mcp/)

**How it works:**
- Admin Panel → Settings → External Tools → Add MCP Server
- Supports **Streamable HTTP transport only** (not stdio/SSE directly)
- Tools exposed by MCP become available to ALL users globally
- OAuth 2.1 authentication supported
- Requires `WEBUI_SECRET_KEY` for OAuth persistence

**Limitations for Multi-Tenant:**
- ❌ MCP tools are global - no per-user/per-group filtering
- ❌ Single API key per MCP server - can't inject per-tenant credentials
- ❌ No built-in tenant isolation for tool access

---

### 2. Open WebUI RBAC & Groups

**Source:** [Groups | Open WebUI](https://docs.openwebui.com/features/rbac/groups/)

**How it works:**
- **Roles:** Admin, User, Pending
- **Groups:** Organizational units with permissions
- **Permissions:** Additive model (union of all group permissions)
- **Resource ACLs:** Models, Knowledge Bases can be restricted to groups

**Useful for Multi-Tenant:**
- ✅ Groups can isolate Models and Knowledge Bases per tenant
- ✅ OAuth group sync (Azure AD, Keycloak) for automatic tenant assignment
- ✅ ACLs support Private/Restricted visibility

**Limitations:**
- ❌ MCP Tools/External Tools cannot be restricted to groups
- ❌ No per-group API credential injection
- ❌ Groups are for sharing, not for tool-level isolation

---

### 3. mcpo - MCP-to-OpenAPI Proxy

**Source:** [mcpo GitHub](https://github.com/open-webui/mcpo)

**What it does:**
- Converts stdio MCP servers to OpenAPI HTTP endpoints
- Adds authentication, documentation, error handling
- Makes local MCP servers accessible from cloud deployments

**Quick Start:**
```bash
uvx mcpo --port 8000 --api-key "top-secret" -- your_mcp_server_command
```

**For Multi-Tenant:**
- ✅ Can run multiple mcpo instances per tenant
- ✅ Each instance has its own API key
- ❌ Still need orchestration layer to route users to correct instance

---

### 4. Sage MCP - Multi-Tenant Platform

**Source:** [Sage MCP](https://medium.com/@manikandan.eshwar/multi-tenant-mcp-servers-why-centralized-management-matters-a813b03b4a52)

**What it does:**
- Open-source multi-tenant MCP hosting platform
- Path-based isolation: `ws://localhost:8000/api/v1/{tenant-slug}/mcp`
- Centralized OAuth management per tenant
- Web UI for managing tenants and connectors

**Architecture:**
- FastAPI backend (Python async)
- React frontend
- PostgreSQL/Supabase database
- Docker & Kubernetes ready with Helm charts

**For Multi-Tenant:**
- ✅ Purpose-built for multi-tenant MCP
- ✅ Per-tenant OAuth credential management
- ✅ Path-based routing for tenant isolation
- ⚠️ Would need integration with Open WebUI

---

### 5. API Gateway Pattern

**Approach:** Custom proxy that intercepts requests and injects per-user credentials

```
┌──────────┐     ┌─────────────────┐     ┌──────────────┐     ┌─────────┐
│ Open     │────▶│ API Gateway     │────▶│ Credential   │────▶│ Backend │
│ WebUI    │     │ (Kong/Custom)   │     │ Injection    │     │ MCP/API │
└──────────┘     └─────────────────┘     └──────────────┘     └─────────┘
                         │                      │
                         ▼                      ▼
                 ┌───────────────┐      ┌──────────────┐
                 │ Auth Service  │      │ Credential   │
                 │ (JWT/OAuth)   │      │ Store (Vault)│
                 └───────────────┘      └──────────────┘
```

**How it works:**
1. User authenticates → JWT contains user ID + tenant memberships
2. Request hits API Gateway
3. Gateway extracts tenant from request context
4. Gateway looks up tenant-specific credentials from Vault/DB
5. Gateway injects credentials into upstream request
6. Backend MCP/API receives request with correct credentials

---

## Architecture Options

### Option A: Multiple Open WebUI Instances (Simplest)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Load Balancer                            │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Open WebUI      │  │ Open WebUI      │  │ Open WebUI      │
│ (Google Tenant) │  │ (MS Tenant)     │  │ (Company C)     │
│                 │  │                 │  │                 │
│ Google MCP      │  │ MS MCP          │  │ C's MCP         │
│ Google Jira Key │  │ MS Jira Key     │  │ C's Jira Key    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

**Pros:**
- ✅ Complete data isolation
- ✅ No code changes needed
- ✅ Each tenant has own config

**Cons:**
- ❌ Internal employees need multiple logins
- ❌ High infrastructure cost (15x instances?)
- ❌ Hard to manage at scale

**Recommendation:** Not viable for 15,000 users with cross-tenant access.

---

### Option B: Custom MCP Proxy Gateway (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Open WebUI                                │
│                    (Single Instance)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Proxy Gateway                             │
│                 (Custom Python/FastAPI)                          │
│                                                                  │
│  1. Extract user identity from request (JWT)                     │
│  2. Look up user's tenant memberships                            │
│  3. Filter available tools based on tenant access                │
│  4. Inject tenant-specific credentials into MCP requests         │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Google MCP      │  │ MS MCP          │  │ Company C MCP   │
│ (mcpo instance) │  │ (mcpo instance) │  │ (mcpo instance) │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

**Components:**
1. **MCP Proxy Gateway** - FastAPI service that:
   - Receives MCP requests from Open WebUI
   - Authenticates user via JWT
   - Queries user-tenant mapping database
   - Routes to appropriate tenant's MCP instance
   - Injects tenant-specific API credentials

2. **Credential Store** - Vault or encrypted database with:
   - Per-tenant API keys (Google Jira key, MS Jira key, etc.)
   - User-tenant membership mappings

3. **mcpo Instances** - One per tenant, each configured with tenant's tools

**Pros:**
- ✅ Single Open WebUI instance
- ✅ Per-tenant credential isolation
- ✅ Internal employees see only their authorized tenants
- ✅ Scalable on Kubernetes

**Cons:**
- ⚠️ Requires custom development
- ⚠️ MCP tool list still global in UI (filtering happens at proxy)

---

### Option C: Sage MCP Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                        Open WebUI                                │
│                    (Single Instance)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Sage MCP                                  │
│              (Multi-Tenant MCP Platform)                         │
│                                                                  │
│  /api/v1/google/mcp   → Google tenant MCP                        │
│  /api/v1/microsoft/mcp → Microsoft tenant MCP                    │
│  /api/v1/companyc/mcp  → Company C tenant MCP                    │
│                                                                  │
│  Centralized OAuth, per-tenant credentials, web management UI    │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:**
- ✅ Purpose-built for multi-tenant MCP
- ✅ Web UI for managing tenants
- ✅ OAuth credential management built-in
- ✅ Open source (Apache 2.0)

**Cons:**
- ⚠️ Still need to integrate with Open WebUI
- ⚠️ User-tenant mapping still needed
- ⚠️ Less control than custom solution

---

## Recommended Architecture

**Option B (Custom MCP Proxy Gateway)** is recommended because:

1. Maximum control over tenant isolation logic
2. Can integrate with existing SSO/OAuth (Azure AD for 15,000 users)
3. User-tenant mapping can come from HR system or custom DB
4. Scales horizontally on Kubernetes
5. Can evolve into Open WebUI Function/Plugin later

---

## Implementation Plan

### Phase 1: Research & PoC (Today)

#### Task 1: Set Up Local MCP Server

**Files:**
- Create: `mcp-poc/docker-compose.yml`

**Step 1: Create PoC directory**

```bash
mkdir -p mcp-poc
cd mcp-poc
```

**Step 2: Create docker-compose with mcpo**

```yaml
# mcp-poc/docker-compose.yml
version: '3.8'

services:
  # Simple filesystem MCP server via mcpo
  mcp-filesystem:
    image: python:3.11-slim
    command: >
      bash -c "pip install mcpo mcp-server-filesystem &&
               mcpo --port 8001 --api-key test-key --
               mcp-server-filesystem /data"
    ports:
      - "8001:8001"
    volumes:
      - ./test-data:/data

volumes:
  test-data:
```

**Step 3: Start and test**

```bash
docker compose up -d
curl http://localhost:8001/docs  # Should show OpenAPI docs
```

**Step 4: Add to Open WebUI**

1. Open WebUI → Admin Panel → Settings → External Tools
2. Click + → Add OpenAPI server
3. URL: `http://host.docker.internal:8001`
4. API Key: `test-key`

---

#### Task 2: Test MCP Tool Visibility

**Step 1: Create test user in different group**

1. Admin Panel → Users → Create test user
2. Create "Google" group and "Microsoft" group
3. Assign test user to "Google" group only

**Step 2: Verify tool visibility**

- Check if MCP tools appear for all users (expected: yes)
- Document that tools are global, confirming need for proxy

---

#### Task 3: Design Proxy Gateway Schema

**Files:**
- Create: `docs/plans/mcp-proxy-gateway-design.md`

**Step 1: Document data models**

```python
# User-Tenant Mapping
class UserTenantAccess:
    user_id: str          # From SSO/OAuth
    tenant_id: str        # "google", "microsoft", etc.
    access_level: str     # "read", "write", "admin"

# Tenant Configuration
class TenantConfig:
    tenant_id: str
    display_name: str
    mcp_endpoint: str     # "http://mcp-google:8001"
    credentials: dict     # Encrypted API keys

# Available Tools per Tenant
class TenantTools:
    tenant_id: str
    tool_name: str        # "jira", "confluence", etc.
    enabled: bool
```

---

### Phase 2: Proxy Gateway Development (This Week)

#### Task 4: Create FastAPI Proxy Skeleton

**Files:**
- Create: `mcp-proxy/main.py`
- Create: `mcp-proxy/requirements.txt`
- Create: `mcp-proxy/Dockerfile`

**Step 1: Create proxy service**

```python
# mcp-proxy/main.py
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBearer
import httpx
import jwt

app = FastAPI(title="MCP Proxy Gateway")
security = HTTPBearer()

# Tenant configuration (move to DB later)
TENANT_CONFIG = {
    "google": {
        "mcp_endpoint": "http://mcp-google:8001",
        "api_key": "google-secret-key"
    },
    "microsoft": {
        "mcp_endpoint": "http://mcp-microsoft:8001",
        "api_key": "ms-secret-key"
    }
}

# User-tenant mapping (move to DB later)
USER_TENANTS = {
    "user@company.com": ["google", "microsoft"],
    "google-employee@google.com": ["google"],
    "ms-employee@microsoft.com": ["microsoft"]
}

def get_user_tenants(token: str) -> list:
    """Extract user and their tenant access from JWT"""
    payload = jwt.decode(token, options={"verify_signature": False})
    user_email = payload.get("email")
    return USER_TENANTS.get(user_email, [])

@app.get("/tools")
async def list_tools(request: Request, token = Depends(security)):
    """List tools available to the current user based on tenant access"""
    tenants = get_user_tenants(token.credentials)
    available_tools = []

    for tenant_id in tenants:
        config = TENANT_CONFIG.get(tenant_id)
        if config:
            # Fetch tools from tenant's MCP endpoint
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{config['mcp_endpoint']}/tools",
                    headers={"Authorization": f"Bearer {config['api_key']}"}
                )
                tools = resp.json()
                for tool in tools:
                    tool["tenant"] = tenant_id
                    available_tools.append(tool)

    return {"tools": available_tools}

@app.post("/tools/{tenant_id}/{tool_name}/execute")
async def execute_tool(
    tenant_id: str,
    tool_name: str,
    request: Request,
    token = Depends(security)
):
    """Execute a tool with tenant-specific credentials"""
    tenants = get_user_tenants(token.credentials)

    if tenant_id not in tenants:
        raise HTTPException(403, "Access denied to this tenant")

    config = TENANT_CONFIG.get(tenant_id)
    if not config:
        raise HTTPException(404, "Tenant not found")

    # Forward request to tenant's MCP with injected credentials
    body = await request.json()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config['mcp_endpoint']}/tools/{tool_name}/execute",
            json=body,
            headers={"Authorization": f"Bearer {config['api_key']}"}
        )
        return resp.json()
```

---

#### Task 5: Integrate with Open WebUI

**Step 1: Register proxy as OpenAPI server**

1. Deploy proxy gateway
2. Add to Open WebUI as External Tool
3. Test tool execution flow

**Step 2: Handle Open WebUI's tool discovery**

- Open WebUI queries `/tools` endpoint
- Proxy filters based on user's JWT
- Only authorized tenant tools returned

---

### Phase 3: Production Hardening (Next Week)

#### Task 6: Add Database for Configuration

- PostgreSQL for tenant configs and user mappings
- HashiCorp Vault for credential storage
- OAuth group sync from Azure AD

#### Task 7: Kubernetes Deployment

- Helm charts for proxy gateway
- Horizontal pod autoscaling
- Network policies for tenant isolation

#### Task 8: Monitoring & Audit

- OpenTelemetry for tracing
- Audit logs for compliance
- Per-tenant usage metrics

---

## Quick Reference

### Key URLs

| Resource | URL |
|----------|-----|
| Open WebUI MCP Docs | https://docs.openwebui.com/features/mcp/ |
| mcpo GitHub | https://github.com/open-webui/mcpo |
| Open WebUI Groups | https://docs.openwebui.com/features/rbac/groups/ |
| Sage MCP | https://github.com/sage-mcp/sage-mcp |

### Commands Cheatsheet

```bash
# Start mcpo proxy for an MCP server
uvx mcpo --port 8001 --api-key "secret" -- mcp-server-command

# Test MCP endpoint
curl http://localhost:8001/docs

# Add to Open WebUI
# Admin Panel → Settings → External Tools → +
```

---

## Open Questions

1. **How does Open WebUI pass user identity to External Tools?**
   - Need to verify JWT/header forwarding

2. **Can Open WebUI Groups restrict External Tool visibility?**
   - Current research suggests no, but needs verification

3. **What's the latency impact of proxy gateway?**
   - Need to benchmark

4. **How to handle tool UI in Open WebUI?**
   - Tools may show globally even if proxy filters execution

---

## Sources

- [MCP Support | Open WebUI](https://docs.openwebui.com/features/mcp/)
- [Groups | Open WebUI](https://docs.openwebui.com/features/rbac/groups/)
- [mcpo GitHub](https://github.com/open-webui/mcpo)
- [Multi-Tenant MCP Servers](https://medium.com/@manikandan.eshwar/multi-tenant-mcp-servers-why-centralized-management-matters-a813b03b4a52)
- [MCP Authorization](https://modelcontextprotocol.io/docs/tutorials/security/authorization)
- [AWS MCP Proxy](https://aws.amazon.com/about-aws/whats-new/2025/10/model-context-protocol-proxy-available/)
