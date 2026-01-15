# Phase 2 Comprehensive Design Document

**Date:** 2026-01-06
**Status:** Draft - Pending Approval
**Goal:** Build Multi-Tenant MCP Proxy Gateway for 15,000 employees

---

## Executive Summary

### The Problem
Open WebUI exposes MCP tools globally to ALL users. For a multi-tenant environment (Google, Microsoft, Company C), we need per-tenant tool isolation and credential injection.

### Key Discovery
**Open WebUI supports `ENABLE_FORWARD_USER_INFO_HEADERS`** which forwards:
- `X-OpenWebUI-User-Name`
- `X-OpenWebUI-User-Id`
- `X-OpenWebUI-User-Email`
- `X-OpenWebUI-User-Role`
- `X-OpenWebUI-Chat-Id`

This enables our proxy to identify users and filter tools accordingly!

---

## Architecture Options Explored

### Option A: Custom FastAPI Proxy (RECOMMENDED)

```
Open WebUI ──▶ FastAPI Proxy ──▶ Per-Tenant MCP Servers
                   │
                   ├── Extract X-OpenWebUI-User-Email
                   ├── Query user's tenant memberships
                   ├── Filter available tools
                   └── Inject tenant credentials
```

**Pros:**
- Full control over logic
- Lightweight, simple
- Easy to debug
- No external dependencies

**Cons:**
- More initial development work

### Option B: MCP Plexus Framework

**Source:** [github.com/Super-I-Tech/mcp_plexus](https://github.com/Super-I-Tech/mcp_plexus)

Built-in multi-tenancy with OAuth 2.1, tenant isolation, encrypted credential storage.

**Pros:**
- Already built for multi-tenancy
- OAuth 2.1 ready
- Encrypted credential storage

**Cons:**
- Requires Redis
- More complex setup
- Less control
- Still in development (missing features)

### Option C: Official Atlassian MCP Server

**Source:** [github.com/atlassian/atlassian-mcp-server](https://github.com/atlassian/atlassian-mcp-server)

Official Atlassian MCP at `https://mcp.atlassian.com/v1/sse`

**Pros:**
- Official, maintained
- OAuth 2.1 built-in
- Respects Jira/Confluence permissions

**Cons:**
- One endpoint for all tenants (can't separate Google Jira from MS Jira)
- Doesn't solve our multi-tenant problem
- Rate limits on free plans

### Recommendation: Option A (Custom FastAPI Proxy)

**Why:**
1. Most flexible for our specific requirements
2. Can use `X-OpenWebUI-User-Email` header directly
3. No external service dependencies
4. Can evolve as requirements change
5. Simple to deploy on existing Kubernetes

---

## Technical Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OPEN WEBUI                                      │
│                          (15,000 employees)                                  │
│                                                                              │
│  Environment: ENABLE_FORWARD_USER_INFO_HEADERS=true                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP + X-OpenWebUI-User-* headers
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP PROXY GATEWAY                                   │
│                         (FastAPI Service)                                    │
│                                                                              │
│  Endpoints:                                                                  │
│  ├── GET  /openapi.json      → OpenAPI spec (filtered per user)             │
│  ├── GET  /tools             → List tools (filtered per user)               │
│  ├── POST /tools/{name}      → Execute tool (with tenant creds)             │
│  └── GET  /health            → Health check                                 │
│                                                                              │
│  Flow:                                                                       │
│  1. Extract X-OpenWebUI-User-Email from request                             │
│  2. Query PostgreSQL: SELECT tenant_id FROM user_tenant_access              │
│  3. Filter tools by tenant membership                                        │
│  4. For execution: inject tenant-specific credentials                        │
│  5. Forward to correct MCP backend                                           │
└─────────────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Google MCP      │  │ Microsoft MCP   │  │ Company C MCP   │
│ (mcpo:8001)     │  │ (mcpo:8002)     │  │ (mcpo:8003)     │
│                 │  │                 │  │                 │
│ Tools:          │  │ Tools:          │  │ Tools:          │
│ - google_jira   │  │ - ms_jira       │  │ - c_jira        │
│ - google_conf   │  │ - ms_conf       │  │ - c_conf        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Request Flow Example

```
1. User "john@company.com" calls tool in Open WebUI

2. Open WebUI sends request to Proxy:
   POST /tools/jira_create_issue
   Headers:
     X-OpenWebUI-User-Email: john@company.com
     X-OpenWebUI-User-Id: user_123
     Content-Type: application/json
   Body: {"project": "PROJ", "summary": "Bug fix"}

3. Proxy extracts email: john@company.com

4. Proxy queries database:
   SELECT tenant_id FROM user_tenant_access
   WHERE user_id = 'john@company.com'
   → Returns: ["google", "microsoft"]

5. Proxy checks: Is "jira_create_issue" from allowed tenant?
   - google_jira_create_issue → allowed (user has google access)
   - ms_jira_create_issue → allowed (user has microsoft access)
   - c_jira_create_issue → BLOCKED (user doesn't have company-c access)

6. Proxy injects credentials for the correct tenant:
   - Gets Google Jira API token from Vault/DB
   - Adds to request headers

7. Proxy forwards to Google MCP server:
   POST http://mcp-google:8001/tools/jira_create_issue
   Headers:
     Authorization: Bearer google-mcp-api-key
     X-Jira-Token: google-jira-api-token
   Body: {"project": "PROJ", "summary": "Bug fix"}

8. Returns response to Open WebUI
```

---

## Data Models

### Database Schema (PostgreSQL)

```sql
-- Tenants table
CREATE TABLE tenants (
    tenant_id VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    mcp_endpoint VARCHAR(255) NOT NULL,
    mcp_api_key VARCHAR(255) NOT NULL,
    credentials JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- User-Tenant access mapping
CREATE TABLE user_tenant_access (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(50) REFERENCES tenants(tenant_id),
    access_level VARCHAR(20) DEFAULT 'read',
    granted_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_email, tenant_id)
);

-- Tenant tools configuration
CREATE TABLE tenant_tools (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) REFERENCES tenants(tenant_id),
    tool_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    enabled BOOLEAN DEFAULT true,
    UNIQUE(tenant_id, tool_name)
);

-- Indexes
CREATE INDEX idx_user_email ON user_tenant_access(user_email);
CREATE INDEX idx_tenant_tools ON tenant_tools(tenant_id);
```

### Sample Data

```sql
-- Insert tenants
INSERT INTO tenants (tenant_id, display_name, mcp_endpoint, mcp_api_key, credentials) VALUES
('google', 'Google', 'http://mcp-google:8001', 'google-api-key',
 '{"jira_url": "https://google.atlassian.net", "jira_token": "vault:google/jira"}'),
('microsoft', 'Microsoft', 'http://mcp-microsoft:8002', 'ms-api-key',
 '{"jira_url": "https://microsoft.atlassian.net", "jira_token": "vault:ms/jira"}'),
('company-c', 'Company C', 'http://mcp-companyc:8003', 'c-api-key',
 '{"jira_url": "https://companyc.atlassian.net", "jira_token": "vault:companyc/jira"}');

-- Insert user-tenant mappings
INSERT INTO user_tenant_access (user_email, tenant_id, access_level) VALUES
('john@company.com', 'google', 'write'),      -- Internal: access to Google
('john@company.com', 'microsoft', 'write'),   -- Internal: access to Microsoft
('sarah@google.com', 'google', 'write'),      -- Google employee: only Google
('mike@microsoft.com', 'microsoft', 'write'), -- MS employee: only Microsoft
('admin@company.com', 'google', 'admin'),     -- Admin: all access
('admin@company.com', 'microsoft', 'admin'),
('admin@company.com', 'company-c', 'admin');
```

---

## API Specification

### GET /tools

Returns filtered list of tools based on user's tenant access.

**Request:**
```http
GET /tools
X-OpenWebUI-User-Email: john@company.com
```

**Response:**
```json
{
  "tools": [
    {
      "name": "google_jira_create_issue",
      "tenant": "google",
      "description": "Create issue in Google Jira"
    },
    {
      "name": "google_jira_search",
      "tenant": "google",
      "description": "Search Google Jira"
    },
    {
      "name": "ms_jira_create_issue",
      "tenant": "microsoft",
      "description": "Create issue in Microsoft Jira"
    }
  ]
}
```

### POST /tools/{tool_name}

Execute a tool with tenant-specific credentials.

**Request:**
```http
POST /tools/google_jira_create_issue
X-OpenWebUI-User-Email: john@company.com
Content-Type: application/json

{
  "project": "PROJ",
  "summary": "Fix login bug",
  "description": "Users cannot log in"
}
```

**Response:**
```json
{
  "success": true,
  "result": {
    "issue_key": "PROJ-123",
    "url": "https://google.atlassian.net/browse/PROJ-123"
  }
}
```

### Error Responses

**403 Forbidden** - User doesn't have access to tenant:
```json
{
  "error": "Access denied",
  "message": "User john@company.com does not have access to tenant 'company-c'"
}
```

**404 Not Found** - Tool doesn't exist:
```json
{
  "error": "Not found",
  "message": "Tool 'unknown_tool' not found"
}
```

---

## Implementation Plan

### Phase 2A: Core Proxy (Days 1-2)

**Files to create:**
```
mcp-proxy/
├── main.py              # FastAPI app
├── config.py            # Configuration
├── models.py            # Pydantic models
├── database.py          # PostgreSQL connection
├── auth.py              # User extraction from headers
├── tenants.py           # Tenant management
├── tools.py             # Tool routing
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

**Tasks:**
1. Create FastAPI skeleton with health endpoint
2. Implement header extraction (X-OpenWebUI-User-Email)
3. Set up PostgreSQL with schema
4. Implement /tools endpoint (list filtered tools)
5. Implement /tools/{name} endpoint (execute with creds)

### Phase 2B: Integration (Days 3-4)

**Tasks:**
1. Set up per-tenant MCP servers with mcpo
2. Configure Open WebUI:
   - Set `ENABLE_FORWARD_USER_INFO_HEADERS=true`
   - Add proxy as External Tool
3. Test end-to-end flow
4. Handle edge cases (missing user, invalid tenant)

### Phase 2C: Testing (Day 5)

**Test Cases:**
1. Google employee → sees only Google tools ✓
2. Microsoft employee → sees only MS tools ✓
3. Internal employee (multi-tenant) → sees both ✓
4. Unknown user → sees no tools (or default) ✓
5. Tool execution → correct credentials injected ✓

---

## Open WebUI Configuration

### Required Environment Variables

```yaml
# docker-compose.yml for Open WebUI
services:
  open-webui:
    environment:
      # CRITICAL: Enable user info forwarding
      - ENABLE_FORWARD_USER_INFO_HEADERS=true

      # CRITICAL: Set secret key for credential encryption
      - WEBUI_SECRET_KEY=your-persistent-secret-key
```

### Adding Proxy as External Tool

1. Admin Panel → Settings → External Tools
2. Click + → Add OpenAPI server
3. URL: `http://mcp-proxy:8000`
4. API Key: (optional, for internal auth)
5. Save

---

## Available MCP Servers for Jira/Atlassian

| Server | Source | Features |
|--------|--------|----------|
| **Official Atlassian** | [atlassian/atlassian-mcp-server](https://github.com/atlassian/atlassian-mcp-server) | OAuth 2.1, respects permissions |
| **sooperset/mcp-atlassian** | [GitHub](https://github.com/sooperset/mcp-atlassian) | Cloud + Server/DC support |
| **aashari/mcp-server-atlassian-jira** | [GitHub](https://github.com/aashari/mcp-server-atlassian-jira) | 51 tools, JQL support |
| **xuanxt/atlassian-mcp** | [GitHub](https://github.com/xuanxt/atlassian-mcp) | 51 tools, Docker ready |

**Recommendation:** Use [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian) - well maintained, supports both Cloud and Server deployments.

---

## Security Considerations

### Credential Storage

**For PoC (Phase 2):**
- Store credentials in PostgreSQL JSONB column
- Encrypt sensitive values at rest

**For Production (Phase 3):**
- Use HashiCorp Vault
- Reference secrets as `vault:path/to/secret`
- Resolve at runtime

### Authentication Flow

```
User Login (SSO/OAuth)
        │
        ▼
   Open WebUI
   (validates JWT)
        │
        ▼ X-OpenWebUI-User-Email header
        │
   MCP Proxy Gateway
   (trusts header from Open WebUI)
        │
        ▼ Injects tenant credentials
        │
   Tenant MCP Server
```

### Network Security (Kubernetes)

```yaml
# Network Policy - only Open WebUI can reach proxy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-proxy-policy
spec:
  podSelector:
    matchLabels:
      app: mcp-proxy
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: open-webui
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Google user sees only Google tools | ✓ |
| MS user sees only MS tools | ✓ |
| Internal user sees authorized tenants only | ✓ |
| Credentials never exposed to users | ✓ |
| Latency < 100ms for tool list | ✓ |
| 99.9% uptime | ✓ |

---

## Sources

- [Open WebUI MCP Support](https://docs.openwebui.com/features/mcp/)
- [Open WebUI Environment Variables](https://docs.openwebui.com/getting-started/env-configuration/)
- [mcpo - MCP to OpenAPI Proxy](https://github.com/open-webui/mcpo)
- [MCP Plexus Multi-Tenant Framework](https://github.com/Super-I-Tech/mcp_plexus)
- [Official Atlassian MCP Server](https://github.com/atlassian/atlassian-mcp-server)
- [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian)
- [Multi-Tenant MCP Discussion](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/193)
