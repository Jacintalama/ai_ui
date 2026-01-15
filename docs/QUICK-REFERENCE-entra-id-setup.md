# Quick Reference: Entra ID Setup for Lukas

**One-page guide for tonight's setup**

---

## Step 1: Azure Portal → App Registration

```
https://portal.azure.com
→ Search "Microsoft Entra ID"
→ App registrations
→ + New registration
```

| Field | Value |
|-------|-------|
| Name | `Open WebUI` |
| Account type | Single tenant (or Multitenant) |
| Redirect URI | `https://ai-ui.coolestdomain.win/oauth/microsoft/callback` |

---

## Step 2: Copy These Values

After registration, copy:

```
Application (client) ID:     ________________________________
Directory (tenant) ID:       ________________________________
Client Secret (create new):  ________________________________
```

---

## Step 3: API Permissions

Add these permissions → **Grant admin consent**:

- [x] User.Read
- [x] email
- [x] openid
- [x] profile
- [x] GroupMember.Read.All

---

## Step 4: Create Security Groups

```
Entra ID → Groups → + New group
```

Create these groups:

| Group Name | Who to Add |
|------------|------------|
| `MCP-GitHub` | Users who need GitHub tools |
| `MCP-Filesystem` | Users who need file access |
| `MCP-Google` | Google tenant users |
| `MCP-Microsoft` | Microsoft tenant users |
| `MCP-Admin` | Full access users |

---

## Step 5: Environment Variables for Open WebUI

```bash
# Add to your deployment
MICROSOFT_CLIENT_ID=<your-client-id>
MICROSOFT_CLIENT_SECRET=<your-client-secret>
MICROSOFT_CLIENT_TENANT_ID=<your-tenant-id>

ENABLE_OAUTH_SIGNUP=true
ENABLE_OAUTH_GROUP_MANAGEMENT=true
ENABLE_OAUTH_GROUP_CREATION=true
ENABLE_FORWARD_USER_INFO_HEADERS=true
BYPASS_MODEL_ACCESS_CONTROL=true
```

---

## Step 6: Test Login

1. Go to https://ai-ui.coolestdomain.win
2. Click "Sign in with Microsoft"
3. Login with your account
4. Check Admin Panel → Users → verify groups appear

---

## Redirect URI (Important!)

Must match EXACTLY:
```
https://ai-ui.coolestdomain.win/oauth/microsoft/callback
```

---

## Done! 🎉

Once configured, users will:
- Login with Microsoft account
- Automatically get assigned to groups
- See only MCP tools they have access to
