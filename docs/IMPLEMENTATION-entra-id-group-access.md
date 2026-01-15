# Entra ID Group-Based Access Control - Implementation Complete

**Date:** January 14, 2026
**Status:** IMPLEMENTED & TESTED

---

## Summary

Multi-tenant access control now supports **Entra ID groups** for 15,000+ users. No more hardcoded user emails!

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. User logs in via Microsoft Entra ID                                 │
│     └── User is member of "MCP-GitHub" and "MCP-Filesystem" groups      │
│                                                                         │
│  2. Open WebUI gets groups from OAuth token                             │
│     └── ENABLE_OAUTH_GROUP_MANAGEMENT=true                              │
│     └── Groups stored in __user__ context                               │
│                                                                         │
│  3. Python Tool forwards groups to MCP Proxy                            │
│     └── X-OpenWebUI-User-Groups: MCP-GitHub,MCP-Filesystem              │
│                                                                         │
│  4. MCP Proxy checks group membership                                   │
│     └── [GROUP-BASED] user@company.com groups=['MCP-GitHub'] -> True    │
│     └── Returns only servers user has access to                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Access Control Priority

1. **Groups** (if X-User-Groups header present) → Group-based access
2. **Hardcoded** (if no groups) → Legacy USER_TENANT_ACCESS fallback

This allows:
- Production: Use Entra ID groups
- Development: Use hardcoded for testing

---

## Test Results (Verified Working)

| Test | Email | Groups Header | Servers | Status |
|------|-------|--------------|---------|--------|
| 1 | test@x.com | MCP-GitHub | 1 | ✅ |
| 2 | test@x.com | MCP-Admin | 11 | ✅ |
| 3 | test@x.com | MCP-GitHub,MCP-Filesystem | 2 | ✅ |
| 4 | joelalama@google.com | (none) | 1 | ✅ Hardcoded fallback |
| 5 | alamajacintg04@gmail.com | (none) | 11 | ✅ Hardcoded fallback |
| 6 | alamajacintg04@gmail.com | MCP-GitHub | 1 | ✅ Groups priority! |

---

## Files Modified

### 1. `mcp-proxy/auth.py`
- Added X-OpenWebUI-User-Groups header parsing
- Added X-User-Groups header parsing (alternative name)
- Groups passed to UserInfo.entra_groups

### 2. `mcp-proxy/tenants.py`
- `user_has_tenant_access()` now prioritizes groups over hardcoded
- Added debug logging: `[GROUP-BASED]` vs `[HARDCODED]`

### 3. `mcp-proxy/main.py`
- Added groups header logging in /servers endpoint
- Groups forwarded to access check functions

### 4. `open-webui-functions/mcp_multi_tenant_bridge.py`
- `_get_user_headers()` now extracts groups from `__user__` context
- Forwards groups via X-OpenWebUI-User-Groups header
- Added `debug_my_context()` tool to view user context

---

## Configuration Steps for 15k Users

### Step 1: Create Entra ID Groups

In Azure Portal → Microsoft Entra ID → Groups:

| Group Name | Description | MCP Access |
|------------|-------------|------------|
| `MCP-GitHub` | GitHub access | github |
| `MCP-Filesystem` | File access | filesystem |
| `MCP-Linear` | Linear issues | linear |
| `MCP-Notion` | Notion docs | notion |
| `MCP-Admin` | Full access | ALL servers |

### Step 2: Configure App Registration

1. Azure Portal → Entra ID → App Registrations
2. Find/create Open WebUI app
3. API Permissions → Add:
   - `User.Read`
   - `GroupMember.Read.All`
4. Token Configuration → Add groups claim:
   - Edit → "groups" → Select "Security groups"
5. Grant admin consent

### Step 3: Configure Open WebUI

Add to environment variables:

```yaml
# Microsoft OAuth
MICROSOFT_CLIENT_ID: "your-client-id"
MICROSOFT_CLIENT_SECRET: "your-client-secret"
MICROSOFT_CLIENT_TENANT_ID: "your-tenant-id"  # NOT "consumers"!

# OAuth Settings
ENABLE_OAUTH_SIGNUP: "true"
OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"

# Group Management (CRITICAL!)
ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
ENABLE_OAUTH_GROUP_CREATION: "true"
OAUTH_GROUP_CLAIM: "groups"

# Forward user info to tools
ENABLE_FORWARD_USER_INFO_HEADERS: "true"
```

### Step 4: Assign Users to Groups

1. Azure Portal → Entra ID → Groups → Select group
2. Members → Add members
3. Search and add users

For bulk assignment:
- Use Azure AD PowerShell
- Use CSV import via Admin Center
- Use Graph API for automation

### Step 5: Verify Setup

1. Login to Open WebUI with Microsoft account
2. Ask: "Debug my context"
3. Should show groups in response
4. Ask: "List my servers"
5. Should show only servers for your groups

---

## Group Mapping Reference

From `tenants.py`:

```python
ENTRA_GROUP_TENANT_MAPPING = {
    "MCP-GitHub": ["github"],
    "MCP-Filesystem": ["filesystem"],
    "MCP-Linear": ["linear"],
    "MCP-Notion": ["notion"],
    "MCP-HubSpot": ["hubspot"],
    "MCP-Pulumi": ["pulumi"],
    "MCP-GitLab": ["gitlab"],
    "MCP-Atlassian": ["atlassian"],
    "MCP-Asana": ["asana"],
    "MCP-SonarQube": ["sonarqube"],
    "MCP-Sentry": ["sentry"],
    "MCP-Admin": [ALL servers],
}
```

---

## Troubleshooting

### Groups not appearing?

1. Check `ENABLE_OAUTH_GROUP_MANAGEMENT=true`
2. Check `OAUTH_GROUP_CLAIM=groups`
3. Verify App Registration has GroupMember.Read.All permission
4. Verify admin consent granted
5. Use "Debug my context" tool to see __user__ contents

### User sees wrong servers?

1. Check MCP Proxy logs: `kubectl logs -n open-webui deployment/mcp-proxy`
2. Look for `[GROUP-BASED]` or `[HARDCODED]` prefix
3. If `[HARDCODED]`, groups not being received

### Testing without Entra ID?

Use curl with headers:
```bash
curl -H "X-OpenWebUI-User-Email: test@x.com" \
     -H "X-User-Groups: MCP-GitHub,MCP-Filesystem" \
     http://localhost:30800/servers
```

---

## Architecture Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   User Login    │────▶│  Microsoft      │────▶│   Open WebUI    │
│   (Browser)     │     │  Entra ID       │     │   (OAuth)       │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                        OAuth Token with Groups          │
                        ┌────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Open WebUI                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Python Tool (mcp_multi_tenant_bridge.py)               │   │
│  │  - Extracts groups from __user__ context                │   │
│  │  - Forwards via X-OpenWebUI-User-Groups header          │   │
│  └────────────────────────┬────────────────────────────────┘   │
└───────────────────────────│─────────────────────────────────────┘
                            │
                            │ X-OpenWebUI-User-Email: user@x.com
                            │ X-OpenWebUI-User-Groups: MCP-GitHub
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       MCP Proxy                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  auth.py: Extract user + groups from headers            │   │
│  │  tenants.py: Check group membership                     │   │
│  │  main.py: Filter servers by access                      │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  [GROUP-BASED] user@x.com groups=['MCP-GitHub'] -> github: ✓   │
│  [GROUP-BASED] user@x.com groups=['MCP-GitHub'] -> filesystem: ✗│
└───────────────────────────│─────────────────────────────────────┘
                            │
                            ▼
                    Only authorized servers returned
```
