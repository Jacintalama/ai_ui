# Enterprise Multi-Tenant Implementation Plan

**Date:** January 15, 2026
**Project:** Open WebUI Multi-Tenant for Highspring
**Target Users:** 15,000 Highspring employees
**Tenants:** Client companies (Google, Microsoft, AcmeCorp, etc.)

---

## Overview

Highspring employees (@highspring.com) need access to multiple client tenants. Each employee may be assigned to one or more client tenants. Data and MCP tools must be isolated per tenant.

**Current State:** Using `consumers` OAuth (personal accounts) for testing
**Target State:** Highspring enterprise Entra ID with group-based tenant access

---

## Architecture

```
Highspring Employee (steve@highspring.com)
         │
         ▼
   Microsoft Entra ID (Highspring Tenant)
         │
         ├── Groups in Token:
         │   - Tenant-Google
         │   - Tenant-AcmeCorp
         │
         ▼
      Open WebUI
         │
         ├── Syncs groups from token
         ├── Filters data by group
         │
         ▼
      MCP Proxy
         │
         ├── Reads user groups
         ├── Returns only tools for assigned tenants
         │
         ▼
   ┌─────────────────────────────────────┐
   │  Google Tools    │  AcmeCorp Tools  │
   │  - Google JIRA   │  - AcmeCorp JIRA │
   │  - Google Notion │  - AcmeCorp Slack│
   └─────────────────────────────────────┘
```

---

## Phase 1: Azure Entra ID Setup

**Owner:** Lukas / IT Team
**Estimated Time:** 1-2 days

### Task 1.1: Entra ID Tenant
- Use existing Highspring Entra ID tenant
- Or create new tenant for this project

### Task 1.2: App Registration
- Register "Open WebUI" app in Azure Portal
- Set redirect URI: `https://ai-ui.coolestdomain.win/oauth/microsoft/callback`
- Enable ID tokens
- Configure "groups" claim in token

### Task 1.3: Create Tenant Security Groups
Create security groups for each client:
```
Tenant-Google
Tenant-Microsoft
Tenant-AcmeCorp
Tenant-ClientX
... (one per client)
```

### Task 1.4: Assign Employees to Groups
Example assignments:
```
steve@highspring.com → Tenant-Google, Tenant-AcmeCorp
jane@highspring.com  → Tenant-Microsoft
bob@highspring.com   → Tenant-Google
```

### Task 1.5: Provide Credentials
Send to dev team:
- MICROSOFT_CLIENT_ID
- MICROSOFT_CLIENT_SECRET
- MICROSOFT_CLIENT_TENANT_ID (Highspring tenant ID)

---

## Phase 2: OAuth Configuration Update

**Owner:** Dev Team
**Estimated Time:** 2-3 hours
**Blocked By:** Phase 1 completion

### Task 2.1: Update Environment Variables
```bash
# Replace consumers with Highspring tenant
MICROSOFT_CLIENT_ID=<new-client-id>
MICROSOFT_CLIENT_SECRET=<new-client-secret>
MICROSOFT_CLIENT_TENANT_ID=<highspring-tenant-id>

# Keep these settings
ENABLE_OAUTH_SIGNUP=true
ENABLE_OAUTH_GROUP_MANAGEMENT=true
ENABLE_OAUTH_GROUP_CREATION=true
OAUTH_GROUP_CLAIM=groups

# Production URL
WEBUI_URL=https://ai-ui.coolestdomain.win
OPENID_PROVIDER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration
```

### Task 2.2: Update Kubernetes Secrets
```bash
kubectl create secret generic open-webui-oauth \
  --from-literal=MICROSOFT_CLIENT_ID=<value> \
  --from-literal=MICROSOFT_CLIENT_SECRET=<value> \
  --from-literal=MICROSOFT_CLIENT_TENANT_ID=<value> \
  -n open-webui --dry-run=client -o yaml | kubectl apply -f -
```

### Task 2.3: Restart Services
```bash
kubectl rollout restart statefulset/open-webui -n open-webui
```

---

## Phase 3: Open WebUI Group Sync

**Owner:** Dev Team
**Estimated Time:** 1-2 hours

### Task 3.1: Verify Group Sync Settings
Confirm these are set in Open WebUI:
- ENABLE_OAUTH_GROUP_MANAGEMENT=true
- ENABLE_OAUTH_GROUP_CREATION=true
- OAUTH_GROUP_CLAIM=groups

### Task 3.2: Test Group Auto-Creation
1. Login with test user who has groups
2. Check Admin Panel → Groups
3. Verify groups from token appear automatically

### Task 3.3: Configure Group Permissions
For each tenant group in Admin Panel:
- Set Workspace Permissions (Models, Knowledge, Tools)
- Set Sharing Permissions
- Set Feature Permissions

---

## Phase 4: MCP Proxy Tenant Mapping

**Owner:** Dev Team
**Estimated Time:** 3-4 hours

### Task 4.1: Update tenants.py
Map Entra ID groups to MCP servers:

```python
ENTRA_GROUP_TENANT_MAPPING = {
    # Each client tenant gets their own tools
    "Tenant-Google": [
        "google-jira",
        "google-notion",
        "google-github"
    ],
    "Tenant-Microsoft": [
        "microsoft-jira",
        "microsoft-azure-devops",
        "microsoft-teams"
    ],
    "Tenant-AcmeCorp": [
        "acmecorp-jira",
        "acmecorp-slack"
    ],
    # Admin group gets all
    "Tenant-Admin": ["*"]
}
```

### Task 4.2: Configure MCP Servers Per Tenant
Each tenant needs their own MCP server configs:
```python
TENANT_SERVERS = {
    "google-jira": MCPServerConfig(
        server_id="google-jira",
        display_name="Google JIRA",
        endpoint_url="https://google.atlassian.net/...",
        api_key_env="GOOGLE_JIRA_API_KEY"
    ),
    "microsoft-jira": MCPServerConfig(
        server_id="microsoft-jira",
        display_name="Microsoft JIRA",
        endpoint_url="https://microsoft.atlassian.net/...",
        api_key_env="MICROSOFT_JIRA_API_KEY"
    ),
    # ... more servers
}
```

### Task 4.3: Deploy Updated MCP Proxy
```bash
kubectl rollout restart deployment/mcp-proxy -n open-webui
```

---

## Phase 5: Testing

**Owner:** Dev Team
**Estimated Time:** 2-3 hours

### Task 5.1: Create Test Scenarios
| User | Groups | Expected Access |
|------|--------|-----------------|
| test1@highspring.com | Tenant-Google | Google tools only |
| test2@highspring.com | Tenant-Microsoft | Microsoft tools only |
| test3@highspring.com | Tenant-Google, Tenant-Microsoft | Both |
| admin@highspring.com | Tenant-Admin | All tools |

### Task 5.2: Test Data Isolation
1. Login as test1 (Google only)
2. Create chat, upload document
3. Login as test2 (Microsoft only)
4. Verify cannot see test1's data

### Task 5.3: Test MCP Tool Filtering
1. Login as test1 (Google only)
2. Verify only Google MCP tools available
3. Verify cannot access Microsoft tools

### Task 5.4: Test Multi-Tenant Access
1. Login as test3 (Google + Microsoft)
2. Verify both tool sets available
3. Verify data from both tenants accessible

---

## Timeline

| Phase | Task | Duration | Dependency |
|-------|------|----------|------------|
| 1 | Azure Entra ID Setup | 1-2 days | None |
| 2 | OAuth Configuration | 2-3 hours | Phase 1 |
| 3 | Group Sync | 1-2 hours | Phase 2 |
| 4 | MCP Proxy Mapping | 3-4 hours | Phase 1 |
| 5 | Testing | 2-3 hours | Phase 2-4 |

**Total:** ~3-4 days (assuming Phase 1 done by Lukas/IT)

---

## Blockers

1. **Phase 1 must be completed first** - We cannot proceed without Highspring Entra ID credentials and tenant groups

2. **Client API Keys needed** - Each tenant's MCP servers need their own API keys (Google's JIRA key, Microsoft's JIRA key, etc.)

---

## Questions for Lukas

1. Do you have an existing Highspring Entra ID tenant we should use?

2. What are the initial client tenants to set up? (Google, Microsoft, ...?)

3. Do you have API keys for each client's services? (JIRA, Notion, etc.)

4. Who will manage group assignments in Azure? (IT team?)

---

## Success Criteria

- [ ] Employees login with @highspring.com accounts
- [ ] Groups from Entra ID token sync to Open WebUI automatically
- [ ] Each employee sees only data for their assigned tenants
- [ ] MCP tools filtered based on tenant group membership
- [ ] One employee can access multiple tenants if assigned
- [ ] New tenants can be added by creating new Azure group + MCP config

---

*Plan Created: January 15, 2026*
