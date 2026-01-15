# OAuth Group-Based Access Control Configuration Plan

**Date:** January 12, 2026
**Status:** Pending - Awaiting Lukas Confirmation

---

## Overview

Configure Open WebUI to automatically sync user groups from Microsoft Entra ID and forward them to MCP Proxy for automatic tool access control.

## The Flow (Automatic)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1. User logs in via Microsoft Entra ID (OAuth)                         │
│     └── joelalama@google.com is in group "MCP-GitHub"                    │
│                                                                          │
│  2. Open WebUI gets user's groups from OAuth token                       │
│     └── ENABLE_OAUTH_GROUP_MANAGEMENT=true                               │
│                                                                          │
│  3. Open WebUI forwards groups in header to MCP Proxy                    │
│     └── X-User-Groups: MCP-GitHub,MCP-Google                             │
│                                                                          │
│  4. MCP Proxy reads header, grants access based on groups                │
│     └── ENTRA_GROUP_TENANT_MAPPING already exists in tenants.py!         │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Microsoft Entra ID Configuration

### Create Security Groups in Entra ID

| Group Name | MCP Access |
|------------|------------|
| `MCP-GitHub` | GitHub tools (26 tools) |
| `MCP-Filesystem` | Filesystem tools (14 tools) |
| `MCP-Google` | Google tenant tools |
| `MCP-Microsoft` | Microsoft tenant tools |
| `MCP-Linear` | Linear issue tracking |
| `MCP-Notion` | Notion workspace |
| `MCP-Admin` | ALL tools (full access) |

### Configure App Registration

1. Go to Azure Portal → Entra ID → App registrations
2. Create or edit app registration for Open WebUI
3. Add API permissions:
   - `User.Read`
   - `GroupMember.Read.All` (for group claims)
4. Configure token claims to include groups

---

## Step 2: Open WebUI Environment Variables

```yaml
# =============================================================================
# MICROSOFT ENTRA ID OAUTH CONFIGURATION
# =============================================================================

# OAuth Provider - Microsoft
MICROSOFT_CLIENT_ID: "your-azure-app-client-id"
MICROSOFT_CLIENT_SECRET: "your-azure-app-client-secret"
MICROSOFT_CLIENT_TENANT_ID: "your-azure-tenant-id"

# Enable OAuth Features
ENABLE_OAUTH_SIGNUP: "true"                    # Auto-create users on first login
OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"          # Merge with existing accounts

# Domain Filtering (Optional)
OAUTH_ALLOWED_DOMAINS: "google.com;microsoft.com;company.com"

# =============================================================================
# GROUP MANAGEMENT (CRITICAL FOR MCP ACCESS CONTROL)
# =============================================================================

ENABLE_OAUTH_GROUP_MANAGEMENT: "true"          # Sync groups from OAuth
ENABLE_OAUTH_GROUP_CREATION: "true"            # Auto-create groups in Open WebUI
OAUTH_GROUP_CLAIM: "groups"                    # Claim name for groups in token

# =============================================================================
# FORWARD USER INFO TO MCP PROXY
# =============================================================================

ENABLE_FORWARD_USER_INFO_HEADERS: "true"       # Forward user email in headers

# The MCP Proxy will receive:
# - X-OpenWebUI-User-Email: user's email
# - X-OpenWebUI-User-Name: user's display name
# - X-OpenWebUI-User-Id: user's ID
```

---

## Step 3: MCP Proxy Configuration

### Already Configured in `tenants.py` (lines 256-289):

```python
ENTRA_GROUP_TENANT_MAPPING: Dict[str, List[str]] = {
    # Entra ID Group Name -> List of server/tenant IDs

    # Local servers
    "MCP-GitHub": ["github"],
    "MCP-Filesystem": ["filesystem"],

    # Tier 1: HTTP servers
    "MCP-Linear": ["linear"],
    "MCP-Notion": ["notion"],
    "MCP-HubSpot": ["hubspot"],
    "MCP-Pulumi": ["pulumi"],
    "MCP-GitLab": ["gitlab"],

    # Tier 2: SSE servers
    "MCP-Atlassian": ["atlassian"],
    "MCP-Asana": ["asana"],

    # Tier 3: stdio servers
    "MCP-SonarQube": ["sonarqube"],
    "MCP-Sentry": ["sentry"],

    # Legacy tenants
    "MCP-Google": ["google"],
    "MCP-Microsoft": ["microsoft"],

    # Admin group gets access to ALL servers
    "MCP-Admin": [
        "github", "filesystem",
        "linear", "notion", "hubspot", "pulumi", "gitlab",
        "atlassian", "asana",
        "sonarqube", "sentry",
        "google", "microsoft"
    ],
}
```

### How MCP Proxy Reads Groups

The MCP Proxy needs to read groups from the `X-User-Groups` header.

**Current Implementation in `auth.py`:**
- Already reads `X-OpenWebUI-User-Email` header
- Need to verify it also reads groups header

**Update Required:**
```python
# In auth.py - extract groups from header
def get_user_groups(request: Request) -> List[str]:
    groups_header = request.headers.get("X-User-Groups", "")
    if groups_header:
        return [g.strip() for g in groups_header.split(",")]
    return []
```

---

## Step 4: Kubernetes Helm Values Update

```yaml
# kubernetes/values-production.yaml

env:
  # Microsoft Entra ID OAuth
  - name: MICROSOFT_CLIENT_ID
    valueFrom:
      secretKeyRef:
        name: oauth-secrets
        key: microsoft-client-id
  - name: MICROSOFT_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: oauth-secrets
        key: microsoft-client-secret
  - name: MICROSOFT_CLIENT_TENANT_ID
    valueFrom:
      secretKeyRef:
        name: oauth-secrets
        key: microsoft-tenant-id

  # OAuth Settings
  - name: ENABLE_OAUTH_SIGNUP
    value: "true"
  - name: ENABLE_OAUTH_GROUP_MANAGEMENT
    value: "true"
  - name: ENABLE_OAUTH_GROUP_CREATION
    value: "true"
  - name: OAUTH_GROUP_CLAIM
    value: "groups"

  # Forward headers to MCP Proxy
  - name: ENABLE_FORWARD_USER_INFO_HEADERS
    value: "true"

  # Model access
  - name: BYPASS_MODEL_ACCESS_CONTROL
    value: "true"
```

---

## Step 5: Create Kubernetes Secret for OAuth

```yaml
# kubernetes/oauth-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: oauth-secrets
  namespace: open-webui
type: Opaque
stringData:
  microsoft-client-id: "your-client-id-here"
  microsoft-client-secret: "your-client-secret-here"
  microsoft-tenant-id: "your-tenant-id-here"
```

---

## Testing Plan

### Test 1: OAuth Login
1. Navigate to Open WebUI
2. Click "Sign in with Microsoft"
3. Verify user is created with correct groups

### Test 2: Group-Based MCP Access
```bash
# User in MCP-GitHub group should see GitHub tools
curl -H "X-OpenWebUI-User-Email: user@google.com" \
     -H "X-User-Groups: MCP-GitHub" \
     http://localhost:30800/github
# Expected: 200 OK with tools

# User NOT in MCP-GitHub group should be denied
curl -H "X-OpenWebUI-User-Email: user@microsoft.com" \
     -H "X-User-Groups: MCP-Microsoft" \
     http://localhost:30800/github
# Expected: 403 Forbidden
```

### Test 3: Admin Access
```bash
# User in MCP-Admin group should see ALL tools
curl -H "X-OpenWebUI-User-Email: admin@company.com" \
     -H "X-User-Groups: MCP-Admin" \
     http://localhost:30800/servers
# Expected: All 11 servers listed
```

---

## Benefits

| Before (Manual) | After (Automatic) |
|-----------------|-------------------|
| Add each user to `tenants.py` | Just add user to Entra ID group |
| Redeploy MCP Proxy for new users | No code changes needed |
| 15,000 users = 15,000 lines of code | 15,000 users = same code |
| Manual sync | Real-time group sync |

---

## Prerequisites Checklist

- [ ] Microsoft Entra ID tenant available
- [ ] App Registration created in Azure
- [ ] Client ID, Secret, Tenant ID obtained
- [ ] Security groups created (MCP-GitHub, MCP-Admin, etc.)
- [ ] Users assigned to appropriate groups
- [ ] Open WebUI configured with OAuth env vars
- [ ] MCP Proxy updated to read groups header

---

## Next Steps

1. **Confirm with Lukas**: Does he have Entra ID set up?
2. **Get Credentials**: Client ID, Secret, Tenant ID from Azure
3. **Create Groups**: In Entra ID portal
4. **Update Kubernetes**: Apply new environment variables
5. **Test**: Verify OAuth login and group-based access
