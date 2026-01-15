# Deployed Environment Findings

**URL:** https://ai-ui.coolestdomain.win/
**Date:** January 12, 2026
**Logged in as:** Jacint Alama (alamajacintg04@gmail.com)

---

## Summary

| Item | Status |
|------|--------|
| Microsoft Entra ID / OAuth | **NOT CONFIGURED** (via environment variables only) |
| LDAP | Available but **DISABLED** |
| Groups | **0 groups** created |
| Users | **4 users** (all admins) |
| Version | v0.6.43 (v0.7.2 available) |

---

## Users (4 Total)

| Name | Email | Role | Last Active |
|------|-------|------|-------------|
| Lukas Herajt | lherajt@gmail.com | admin | 8 hours ago |
| Jacint Alama | alamajacintg04@gmail.com | admin | Active now |
| Clarenz Bacalla | clidebacalla@gmail.com | admin | 3 days ago |
| Jumar James | jumar.designer@gmail.com | admin | 4 days ago |

**Note:** All users have @gmail.com emails. No @google.com or @microsoft.com users.

---

## Groups

- **0 groups configured**
- Groups feature is available: "Organize your users - Use groups to group your users and assign permissions"
- Default permissions applies to all users with the "user" role

---

## Authentication Settings

| Setting | Value |
|---------|-------|
| Default User Role | `pending` |
| Default Group | None |
| Enable New Sign Ups | **DISABLED** |
| LDAP | **DISABLED** |
| JWT Expiration | 4 weeks |
| Enable API Keys | DISABLED |

---

## OAuth / Microsoft Entra ID

**NOT visible in UI** - OAuth is configured via environment variables only:

```yaml
# These would need to be set in the deployment:
MICROSOFT_CLIENT_ID: "..."
MICROSOFT_CLIENT_SECRET: "..."
MICROSOFT_CLIENT_TENANT_ID: "..."
ENABLE_OAUTH_SIGNUP: "true"
ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
```

The UI only shows LDAP toggle, not OAuth settings.

---

## Available Features

### Database Settings
- Import Config from JSON File
- Export Config to JSON File
- Download Database
- Export All Chats (All Users)
- **Export Users** (can export user list)

### External Tools
- Tool servers can use OAuth authentication
- Visibility can be set to Private/Public with Groups

### Connections
- OpenAI API: Enabled (https://api.openai.com/v1)
- Ollama API: Enabled (http://localhost:11434)
- Direct Connections: Disabled

---

## What Needs to Be Done for Multi-Tenant

### Option 1: Use Open WebUI Groups (Manual)
1. Create groups in UI: MCP-GitHub, MCP-Google, MCP-Microsoft
2. Assign users to groups manually
3. Configure tool visibility per group

### Option 2: Enable OAuth with Entra ID (Automatic)
1. Set environment variables for Microsoft OAuth
2. Enable `ENABLE_OAUTH_GROUP_MANAGEMENT=true`
3. Groups sync automatically from Entra ID
4. MCP Proxy reads groups from headers

### Recommendation
Ask Lukas if they have Microsoft Entra ID set up. If yes, Option 2 is better for 15,000 users.

---

## Screenshots

- `deployed-env-groups-empty.png` - Shows 0 groups configured
- `deployed-env-database-export.png` - Shows export options including Export Users
