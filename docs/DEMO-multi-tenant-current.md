# Multi-Tenant MCP Demo - Current Setup

**Date:** January 12, 2026
**Status:** Working

---

## Architecture

```
┌─────────────────┐      ┌─────────────────────┐      ┌─────────────────┐
│                 │      │                     │      │                 │
│   Open WebUI    │─────►│    MCP PROXY        │─────►│  Tool Servers   │
│                 │      │   (mcp-proxy:8000)  │      │                 │
│  Sends header:  │      │                     │      │  - GitHub       │
│  X-OpenWebUI-   │      │  1. Read user email │      │  - Filesystem   │
│  User-Email     │      │  2. Check tenants.py│      │  - Linear*      │
│                 │      │  3. Filter tools    │      │  - Notion*      │
└─────────────────┘      └─────────────────────┘      └─────────────────┘

* External tools need API keys
```

---

## Current User Configuration

File: `mcp-proxy/tenants.py`

| User Email | Tenant Access | Sees These Servers |
|------------|---------------|-------------------|
| `alamajacintg04@gmail.com` | Admin (all) | ALL 11 servers |
| `joelalama@google.com` | github | GitHub only (1 server) |
| `miketest@microsoft.com` | microsoft | None (no servers for microsoft) |

---

## Test Commands

### Test 1: No User (Anonymous)
```bash
curl -s http://localhost:30800/servers
```
**Expected:** Empty list, message about missing headers

---

### Test 2: Joel (Google - GitHub only)
```bash
curl -s -H "X-OpenWebUI-User-Email: joelalama@google.com" \
  http://localhost:30800/servers
```
**Expected:** 1 server (GitHub)

```json
{
  "total_servers": 1,
  "servers": [
    {"id": "github", "name": "GitHub", "tier": "local"}
  ]
}
```

---

### Test 3: Admin (Full Access)
```bash
curl -s -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
  http://localhost:30800/servers
```
**Expected:** 11 servers (all)

---

### Test 4: Mike (Microsoft - No servers)
```bash
curl -s -H "X-OpenWebUI-User-Email: miketest@microsoft.com" \
  http://localhost:30800/servers
```
**Expected:** 0 servers

---

## How to Add a New User

### Step 1: Edit tenants.py

```python
# File: mcp-proxy/tenants.py

USER_TENANT_ACCESS: List[UserTenantAccess] = [
    # ... existing users ...

    # Add new user - give them github access
    UserTenantAccess("newuser@company.com", "github", "write"),

    # Give them filesystem access too
    UserTenantAccess("newuser@company.com", "filesystem", "write"),
]
```

### Step 2: Rebuild and Redeploy

```bash
# Rebuild image
docker build -t mcp-proxy:local ./mcp-proxy

# Restart deployment
kubectl rollout restart deployment/mcp-proxy -n open-webui
```

### Step 3: Test

```bash
curl -s -H "X-OpenWebUI-User-Email: newuser@company.com" \
  http://localhost:30800/servers
```

---

## How to Add a New Server to a Tenant

### Example: Give Joel access to Filesystem

```python
# In tenants.py, add:
UserTenantAccess("joelalama@google.com", "filesystem", "write"),
```

Now Joel sees: GitHub + Filesystem (2 servers)

---

## Server IDs Available

| Server ID | Display Name | Status |
|-----------|--------------|--------|
| `github` | GitHub | Working (local) |
| `filesystem` | Filesystem | Working (local) |
| `linear` | Linear | Needs API key |
| `notion` | Notion | Needs API key |
| `hubspot` | HubSpot | Needs API key |
| `gitlab` | GitLab | Needs API key |
| `pulumi` | Pulumi | Needs API key |
| `atlassian` | Atlassian | Needs API key |
| `asana` | Asana | Needs API key |
| `sentry` | Sentry | Needs API key |
| `sonarqube` | SonarQube | Needs API key |

---

## Quick Test Script

Save and run this:

```bash
#!/bin/bash
echo "=== Multi-Tenant Test ==="
echo ""

echo "1. Anonymous (no header):"
curl -s http://localhost:30800/servers | grep total_servers
echo ""

echo "2. Joel (github only):"
curl -s -H "X-OpenWebUI-User-Email: joelalama@google.com" \
  http://localhost:30800/servers | grep total_servers
echo ""

echo "3. Admin (all servers):"
curl -s -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
  http://localhost:30800/servers | grep total_servers
echo ""

echo "4. Mike (no servers):"
curl -s -H "X-OpenWebUI-User-Email: miketest@microsoft.com" \
  http://localhost:30800/servers | grep total_servers
```

---

## Verify in Open WebUI

1. Login as `joelalama@google.com`
2. Go to chat, click the tools icon
3. Should see only GitHub tools (not Linear, Notion, etc.)

4. Login as `alamajacintg04@gmail.com` (admin)
5. Go to chat, click the tools icon
6. Should see ALL tools

---

## Troubleshooting

### User sees all tools?
- Check Open WebUI has `ENABLE_FORWARD_USER_INFO_HEADERS=true`
- Verify only MCP Proxy Gateway is in External Tools (no direct connections)

### User sees no tools?
- Check user email is in `tenants.py`
- Check the tenant_id matches a server_id

### Check MCP Proxy logs:
```bash
kubectl logs -n open-webui deployment/mcp-proxy --tail=50
```

Look for:
```
=== /servers request ===
  User email: joelalama@google.com
  Checking joelalama@google.com access to github: True
  Returning 1 servers for user joelalama@google.com
```
