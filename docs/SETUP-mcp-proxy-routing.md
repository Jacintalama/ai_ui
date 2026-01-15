# Setup: Route Tools Through MCP Proxy

**Goal:** All MCP tools go through MCP Proxy for multi-tenant filtering

---

## Current Problem

```
Open WebUI → Direct to Tools (NO FILTERING)
```

## Target Setup

```
Open WebUI → MCP Proxy → Tools (WITH FILTERING)
```

---

## Step 1: Check MCP Proxy is Running

```bash
# On Kubernetes
kubectl get pods -n open-webui | grep mcp-proxy

# Expected output:
# mcp-proxy-xxxxx   1/1   Running   0   ...
```

```bash
# Test MCP Proxy is responding
curl http://localhost:30800/health

# Expected: {"status": "healthy"}
```

---

## Step 2: Remove Direct Tool Connections from Open WebUI

1. Login to Open WebUI as **Admin**
2. Go to **Admin Panel** → **Settings** → **External Tools**
3. Click on **Manage Tool Servers**
4. **DELETE** all existing direct connections:
   - GitHub (direct)
   - Linear (direct)
   - GitLab (direct)
   - Notion (direct)
   - HubSpot (direct)
   - Pulumi (direct)
   - Atlassian (direct)
   - Asana (direct)

---

## Step 3: Add MCP Proxy as ONLY Connection

1. In **External Tools** → **Manage Tool Servers**
2. Click **+** to add new connection
3. Configure:

| Field | Value |
|-------|-------|
| **Type** | OpenAPI |
| **URL** | `http://mcp-proxy:8000` (Kubernetes) or `http://localhost:30800` |
| **Name** | `MCP Proxy Gateway` |
| **Description** | `Multi-tenant MCP tool gateway` |
| **Auth** | None (internal network) |

4. Click **Save**

---

## Step 4: Verify MCP Proxy Shows Servers

After adding, you should see these servers available through MCP Proxy:

| Server | Tools | URL Pattern |
|--------|-------|-------------|
| GitHub | 26 | `/github/*` |
| Filesystem | 14 | `/filesystem/*` |
| Linear | varies | `/linear/*` |
| etc. | | |

---

## Step 5: Test Multi-Tenant Filtering

### Test as Admin (alamajacintg04@gmail.com)
- Should see: **ALL tools** from all servers

### Test as Joel (joelalama@google.com)
- Should see: **GitHub tools only** (26 tools)
- Should NOT see: Filesystem, Linear, etc.

### Test as Mike (miketest@microsoft.com)
- Should see: **No tools** (Microsoft tenant not configured with servers)

---

## How Filtering Works

```
1. User logs into Open WebUI
2. User opens tool selector
3. Open WebUI requests tools from MCP Proxy
4. MCP Proxy receives request with headers:
   - X-OpenWebUI-User-Email: joelalama@google.com
   - X-OpenWebUI-User-Name: Joel Alama
5. MCP Proxy checks tenants.py:
   - Joel's email → google tenant → github access only
6. MCP Proxy returns ONLY GitHub tools
7. User sees filtered tool list
```

---

## Tenant Configuration (tenants.py)

Current mapping in `mcp-proxy/tenants.py`:

```python
USER_TENANT_ACCESS = [
    # Admin - full access
    UserTenantAccess("alamajacintg04@gmail.com", "github", "admin"),
    UserTenantAccess("alamajacintg04@gmail.com", "filesystem", "admin"),

    # Joel (Google) - github only
    UserTenantAccess("joelalama@google.com", "google", "write"),
    UserTenantAccess("joelalama@google.com", "github", "write"),

    # Mike (Microsoft) - microsoft only (no servers yet)
    UserTenantAccess("miketest@microsoft.com", "microsoft", "write"),
]
```

---

## Troubleshooting

### Tools not showing?
1. Check MCP Proxy is running: `kubectl logs -n open-webui deployment/mcp-proxy`
2. Check Open WebUI can reach MCP Proxy
3. Verify user email in headers

### All tools showing for everyone?
1. Check `ENABLE_FORWARD_USER_INFO_HEADERS=true` in Open WebUI
2. Check MCP Proxy is receiving headers
3. Check tenants.py configuration

### Connection refused?
1. Check service name: `mcp-proxy` in Kubernetes
2. Check port: `8000` internal, `30800` external
3. Check namespace: `open-webui`

---

## Summary

| Before | After |
|--------|-------|
| 9 direct connections | 1 MCP Proxy connection |
| No filtering | Multi-tenant filtering |
| Everyone sees all tools | Users see only their tools |
