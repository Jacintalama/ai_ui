# Report for Lukas - January 12, 2026

**Prepared by:** Jacint Alama
**Project:** Open WebUI + MCP Multi-Tenant Integration

---

## Executive Summary

We have completed the research and preparation for **automatic multi-tenant authentication** using Microsoft Entra ID. Once you set up Entra ID tonight, users will be able to:

1. ✅ Login with Microsoft account (one click)
2. ✅ Automatically get assigned to groups
3. ✅ See only the MCP tools they have permission to use
4. ✅ No manual user management needed - scales to 15,000+ users

---

## What We Accomplished Today

### 1. Research & Documentation

| Task | Status | Details |
|------|--------|---------|
| Scraped Open WebUI docs | ✅ Done | Found OAuth, LDAP, SCIM support |
| Analyzed your deployed site | ✅ Done | ai-ui.coolestdomain.win |
| Analyzed your GitHub repo | ✅ Done | TheLukasHenry/ai_ui |
| Created setup guides | ✅ Done | Step-by-step instructions |

### 2. Key Findings

**Your Deployed Environment (ai-ui.coolestdomain.win):**
- Version: v0.6.43 (v0.7.2 available)
- Users: 4 (Lukas, Jacint, Clarenz, Jumar) - all admins
- Groups: 0 configured
- OAuth: NOT configured yet (needs environment variables)

**Your Repository (TheLukasHenry/ai_ui):**
- Standard Open WebUI fork
- No custom MCP integration yet
- Ready to add OAuth configuration

### 3. Microsoft Entra ID Research

**Good News:** Entra ID FREE tier is enough for our needs!

| Feature | Free Tier |
|---------|-----------|
| User & Group Management | ✅ Up to 500,000 |
| OAuth / OpenID Connect | ✅ Full support |
| Single Sign-On | ✅ Included |
| App Registration | ✅ Unlimited |
| Price | **FREE** |

---

## Tonight's Plan

### Phase 1: You Set Up Entra ID (30 mins)

**Where:** Azure Portal (https://portal.azure.com)

**Steps:**
```
1. Search "Microsoft Entra ID" in Azure Portal
2. Go to "App registrations" → "New registration"
3. Fill in:
   - Name: "Open WebUI"
   - Redirect URI: https://ai-ui.coolestdomain.win/oauth/microsoft/callback
4. Copy the Client ID and Tenant ID
5. Create a Client Secret (Certificates & secrets)
6. Add API Permissions:
   - User.Read
   - email, openid, profile
   - GroupMember.Read.All
7. Click "Grant admin consent"
8. Create Security Groups:
   - MCP-GitHub
   - MCP-Admin
   - (others as needed)
```

**What You'll Have:**
```
Client ID:     ________________________________
Client Secret: ________________________________
Tenant ID:     ________________________________
```

### Phase 2: I Configure Open WebUI (15 mins)

Once you give me the credentials, I'll add them to your deployment:

```yaml
MICROSOFT_CLIENT_ID: "your-client-id"
MICROSOFT_CLIENT_SECRET: "your-secret"
MICROSOFT_CLIENT_TENANT_ID: "your-tenant"
ENABLE_OAUTH_SIGNUP: "true"
ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
ENABLE_FORWARD_USER_INFO_HEADERS: "true"
```

### Phase 3: Test Together (15 mins)

1. Go to ai-ui.coolestdomain.win
2. Click "Sign in with Microsoft"
3. Login with your Microsoft account
4. Verify user created with groups
5. Test MCP tool filtering

---

## How It Will Work After Tonight

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTOMATIC USER FLOW                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User clicks "Sign in with Microsoft"                          │
│                      │                                          │
│                      ▼                                          │
│  Microsoft Entra ID authenticates                              │
│  Returns: email, name, groups                                  │
│                      │                                          │
│                      ▼                                          │
│  Open WebUI creates/updates user                               │
│  Syncs group membership automatically                          │
│                      │                                          │
│                      ▼                                          │
│  User accesses MCP tools                                       │
│  Tools filtered by group membership                            │
│                      │                                          │
│                      ▼                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ User in MCP-GitHub group  → Sees GitHub tools (26)      │   │
│  │ User in MCP-Admin group   → Sees ALL tools (40+)        │   │
│  │ User in MCP-Google group  → Sees Google tenant tools    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Groups to Create in Entra ID

| Group Name | Access Level | Who Should Be In |
|------------|--------------|------------------|
| `MCP-Admin` | ALL tools | Admins, developers |
| `MCP-GitHub` | GitHub tools (26) | Developers |
| `MCP-Filesystem` | File tools (14) | Power users |
| `MCP-Google` | Google tenant | Google employees |
| `MCP-Microsoft` | Microsoft tenant | Microsoft employees |

---

## Benefits After Setup

### Before (Manual)
- ❌ Add each user to code manually
- ❌ Redeploy for new users
- ❌ 15,000 users = 15,000 lines of code
- ❌ Error-prone

### After (Automatic)
- ✅ Users login with Microsoft - auto created
- ✅ Groups sync from Entra ID
- ✅ No code changes for new users
- ✅ Add user to group = instant access
- ✅ Scales to 15,000+ users easily

---

## Files Prepared for You

| File | Purpose |
|------|---------|
| `QUICK-REFERENCE-entra-id-setup.md` | One-page guide (print this!) |
| `SETUP-GUIDE-oauth-multi-tenant.md` | Detailed step-by-step |
| `TONIGHT-PLAN-2026-01-12.md` | Tonight's action plan |
| `microsoft-entra-id-free-tier.md` | Free tier information |

---

## Questions to Confirm

1. **Redirect URI** - Is this correct?
   ```
   https://ai-ui.coolestdomain.win/oauth/microsoft/callback
   ```

2. **Single or Multi-tenant?**
   - Single = Only your organization can login
   - Multi = Any Microsoft account can login

3. **Default User Role**
   - `pending` = Admin must approve new users
   - `user` = Auto-approved with user role

---

## After Tonight's Setup

### Immediate (Tonight)
- ✅ OAuth login working
- ✅ Users can sign in with Microsoft
- ✅ Groups synced from Entra ID

### Next Steps (Future)
- Connect MCP Proxy to deployed environment
- Add more MCP servers (Linear, Notion, Sentry)
- Configure API keys for external services
- Production hardening

---

## Contact

**Jacint:** Ready to help configure once you have the Entra ID credentials!

Just send me:
1. Client ID
2. Client Secret
3. Tenant ID

And I'll configure it immediately.

---

## Quick Reference Card

```
╔═══════════════════════════════════════════════════════════════╗
║             TONIGHT'S SETUP - QUICK REFERENCE                 ║
╠═══════════════════════════════════════════════════════════════╣
║                                                               ║
║  STEP 1: Azure Portal → Microsoft Entra ID                   ║
║          → App registrations → New registration              ║
║                                                               ║
║  STEP 2: Redirect URI:                                       ║
║          https://ai-ui.coolestdomain.win/oauth/microsoft/callback
║                                                               ║
║  STEP 3: Copy these values:                                  ║
║          • Client ID                                         ║
║          • Client Secret (create new)                        ║
║          • Tenant ID                                         ║
║                                                               ║
║  STEP 4: API Permissions → Add:                              ║
║          • User.Read                                         ║
║          • email, openid, profile                            ║
║          • GroupMember.Read.All                              ║
║          → Grant admin consent                               ║
║                                                               ║
║  STEP 5: Create groups:                                      ║
║          • MCP-Admin                                         ║
║          • MCP-GitHub                                        ║
║                                                               ║
║  STEP 6: Send credentials to Jacint → Done!                  ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```
