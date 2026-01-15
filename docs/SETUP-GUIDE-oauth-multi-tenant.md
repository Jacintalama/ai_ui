# OAuth Multi-Tenant Setup Guide for Lukas

**Date:** January 12, 2026
**Prepared by:** Jacint Alama
**For:** Lukas Herajt

---

## Overview

This guide will help you set up automatic multi-tenant authentication using Microsoft Entra ID. Once configured:

- Users login via Microsoft OAuth
- Their Entra ID groups determine which MCP tools they can access
- No manual user configuration needed
- Scales to 15,000+ users automatically

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER LOGIN FLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. User clicks "Sign in with Microsoft"                                │
│                        │                                                 │
│                        ▼                                                 │
│  2. Microsoft Entra ID authenticates user                               │
│     └── Returns: email, name, groups (MCP-GitHub, MCP-Admin, etc.)      │
│                        │                                                 │
│                        ▼                                                 │
│  3. Open WebUI receives user info + groups                              │
│     └── Creates/updates user account                                    │
│     └── Syncs group membership                                          │
│                        │                                                 │
│                        ▼                                                 │
│  4. User accesses MCP tools                                             │
│     └── Open WebUI sends X-User-Groups header to MCP Proxy              │
│     └── MCP Proxy filters tools based on groups                         │
│                        │                                                 │
│                        ▼                                                 │
│  5. User sees only tools they have access to                            │
│     └── MCP-GitHub group → GitHub tools                                 │
│     └── MCP-Admin group → ALL tools                                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Microsoft Entra ID Setup (Azure Portal)

### Step 1.1: Access Entra ID

1. Go to https://portal.azure.com
2. Search for **"Microsoft Entra ID"** in the top search bar
3. Click on it to open

### Step 1.2: Create App Registration

1. In Entra ID, click **"App registrations"** in left menu
2. Click **"+ New registration"**
3. Fill in:
   - **Name:** `Open WebUI Production` (or any name)
   - **Supported account types:** Select based on your needs:
     - "Single tenant" = Only your organization
     - "Multitenant" = Any Microsoft account
   - **Redirect URI:**
     - Type: `Web`
     - URL: `https://ai-ui.coolestdomain.win/oauth/microsoft/callback`
4. Click **"Register"**

### Step 1.3: Note Down Important Values

After registration, you'll see:

| Field | Where to Find | Example |
|-------|---------------|---------|
| **Application (client) ID** | Overview page | `12345678-abcd-1234-efgh-123456789abc` |
| **Directory (tenant) ID** | Overview page | `87654321-dcba-4321-hgfe-cba987654321` |

**Save these! You'll need them later.**

### Step 1.4: Create Client Secret

1. In your app registration, click **"Certificates & secrets"**
2. Click **"+ New client secret"**
3. Add description: `Open WebUI Secret`
4. Select expiration: `24 months` (recommended)
5. Click **"Add"**
6. **IMPORTANT:** Copy the **Value** immediately! It won't be shown again.

| Field | Value |
|-------|-------|
| **Client Secret** | `abc123~xxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |

### Step 1.5: Configure API Permissions

1. Click **"API permissions"** in left menu
2. Click **"+ Add a permission"**
3. Select **"Microsoft Graph"**
4. Select **"Delegated permissions"**
5. Search and add these permissions:
   - ✅ `User.Read` (usually already added)
   - ✅ `email`
   - ✅ `openid`
   - ✅ `profile`
   - ✅ `GroupMember.Read.All` (for group sync)
6. Click **"Add permissions"**
7. Click **"Grant admin consent for [Your Organization]"** (if you're admin)

### Step 1.6: Configure Token Claims (Optional but Recommended)

To include groups in the token:

1. Click **"Token configuration"** in left menu
2. Click **"+ Add groups claim"**
3. Select:
   - ✅ Security groups
   - ✅ Groups assigned to the application
4. Under "Customize token properties by type":
   - ID: Select **"Group ID"**
   - Access: Select **"Group ID"**
   - SAML: Select **"Group ID"**
5. Click **"Add"**

---

## Part 2: Create Security Groups

### Step 2.1: Create Groups in Entra ID

1. In Entra ID, click **"Groups"** in left menu
2. Click **"+ New group"**
3. Create each of these groups:

| Group Name | Type | Description |
|------------|------|-------------|
| `MCP-GitHub` | Security | Access to GitHub MCP tools |
| `MCP-Filesystem` | Security | Access to Filesystem MCP tools |
| `MCP-Google` | Security | Access to Google tenant tools |
| `MCP-Microsoft` | Security | Access to Microsoft tenant tools |
| `MCP-Linear` | Security | Access to Linear tools |
| `MCP-Notion` | Security | Access to Notion tools |
| `MCP-Admin` | Security | Full access to ALL MCP tools |

### Step 2.2: Add Users to Groups

1. Open each group
2. Click **"Members"** → **"+ Add members"**
3. Search and add users

**Example:**
- Joel Alama → Add to `MCP-GitHub`, `MCP-Google`
- Mike Test → Add to `MCP-Microsoft`
- Admin User → Add to `MCP-Admin`

---

## Part 3: Configure Open WebUI

### Step 3.1: Environment Variables

Add these to your deployment (docker-compose.yaml or hosting platform):

```yaml
# =============================================================================
# MICROSOFT ENTRA ID OAUTH CONFIGURATION
# =============================================================================

# From App Registration (Step 1.3 and 1.4)
MICROSOFT_CLIENT_ID: "YOUR_CLIENT_ID_HERE"
MICROSOFT_CLIENT_SECRET: "YOUR_CLIENT_SECRET_HERE"
MICROSOFT_CLIENT_TENANT_ID: "YOUR_TENANT_ID_HERE"

# =============================================================================
# OAUTH SETTINGS
# =============================================================================

# Enable OAuth signup (create users on first login)
ENABLE_OAUTH_SIGNUP: "true"

# Merge accounts with same email
OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true"

# Enable group management (CRITICAL for MCP access control)
ENABLE_OAUTH_GROUP_MANAGEMENT: "true"

# Auto-create groups from Entra ID
ENABLE_OAUTH_GROUP_CREATION: "true"

# Claim name for groups in token
OAUTH_GROUP_CLAIM: "groups"

# Optional: Restrict to specific domains
# OAUTH_ALLOWED_DOMAINS: "google.com;microsoft.com;yourcompany.com"

# =============================================================================
# USER HEADERS FOR MCP PROXY
# =============================================================================

# Forward user info to MCP Proxy (CRITICAL)
ENABLE_FORWARD_USER_INFO_HEADERS: "true"

# Allow all users to see all models
BYPASS_MODEL_ACCESS_CONTROL: "true"

# =============================================================================
# GENERAL SETTINGS
# =============================================================================

# Default role for new users
DEFAULT_USER_ROLE: "user"

# Enable new signups via OAuth
ENABLE_SIGNUP: "true"
```

### Step 3.2: Update docker-compose.yaml

If using Docker Compose, update your `docker-compose.yaml`:

```yaml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    environment:
      # ... existing env vars ...

      # Microsoft OAuth
      - MICROSOFT_CLIENT_ID=${MICROSOFT_CLIENT_ID}
      - MICROSOFT_CLIENT_SECRET=${MICROSOFT_CLIENT_SECRET}
      - MICROSOFT_CLIENT_TENANT_ID=${MICROSOFT_CLIENT_TENANT_ID}

      # OAuth Settings
      - ENABLE_OAUTH_SIGNUP=true
      - OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
      - ENABLE_OAUTH_GROUP_MANAGEMENT=true
      - ENABLE_OAUTH_GROUP_CREATION=true
      - OAUTH_GROUP_CLAIM=groups

      # User Headers
      - ENABLE_FORWARD_USER_INFO_HEADERS=true
      - BYPASS_MODEL_ACCESS_CONTROL=true
```

### Step 3.3: Create .env File

Create a `.env` file with your secrets:

```bash
# .env file (DO NOT COMMIT TO GIT!)
MICROSOFT_CLIENT_ID=12345678-abcd-1234-efgh-123456789abc
MICROSOFT_CLIENT_SECRET=abc123~xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MICROSOFT_CLIENT_TENANT_ID=87654321-dcba-4321-hgfe-cba987654321
```

---

## Part 4: Configure MCP Proxy (Already Done!)

The MCP Proxy already has group-to-server mapping in `tenants.py`:

```python
ENTRA_GROUP_TENANT_MAPPING = {
    "MCP-GitHub": ["github"],
    "MCP-Filesystem": ["filesystem"],
    "MCP-Google": ["google"],
    "MCP-Microsoft": ["microsoft"],
    "MCP-Admin": ["github", "filesystem", "google", "microsoft", ...],
}
```

**No changes needed** - just ensure MCP Proxy is deployed alongside Open WebUI.

---

## Part 5: Testing

### Step 5.1: Test OAuth Login

1. Go to https://ai-ui.coolestdomain.win
2. Click **"Sign in with Microsoft"**
3. Login with your Microsoft account
4. Verify you're logged in

### Step 5.2: Verify Groups Synced

1. Go to **Admin Panel** → **Users**
2. Click on your user
3. Check that groups are visible

### Step 5.3: Test MCP Access

```bash
# Test as user in MCP-GitHub group
curl -H "X-OpenWebUI-User-Email: user@company.com" \
     -H "X-User-Groups: MCP-GitHub" \
     https://your-mcp-proxy/github
# Should return GitHub tools

# Test as user NOT in MCP-GitHub group
curl -H "X-OpenWebUI-User-Email: user@company.com" \
     -H "X-User-Groups: MCP-Microsoft" \
     https://your-mcp-proxy/github
# Should return 403 Forbidden
```

---

## Part 6: Troubleshooting

### Issue: "Sign in with Microsoft" button not showing

**Solution:** Check that `MICROSOFT_CLIENT_ID` is set correctly.

### Issue: Login fails with redirect error

**Solution:** Verify the Redirect URI in App Registration matches exactly:
```
https://ai-ui.coolestdomain.win/oauth/microsoft/callback
```

### Issue: Groups not syncing

**Solution:**
1. Check `ENABLE_OAUTH_GROUP_MANAGEMENT=true`
2. Verify `GroupMember.Read.All` permission is granted
3. Ensure "Grant admin consent" was clicked

### Issue: User created but no groups

**Solution:**
1. Check Token Configuration includes groups claim
2. Verify user is actually in groups in Entra ID

---

## Summary Checklist

### Entra ID (Azure Portal)
- [ ] App Registration created
- [ ] Client ID noted
- [ ] Client Secret created and noted
- [ ] Tenant ID noted
- [ ] API Permissions added (User.Read, email, openid, profile, GroupMember.Read.All)
- [ ] Admin consent granted
- [ ] Token configuration includes groups
- [ ] Security groups created (MCP-GitHub, MCP-Admin, etc.)
- [ ] Users added to appropriate groups

### Open WebUI Deployment
- [ ] MICROSOFT_CLIENT_ID set
- [ ] MICROSOFT_CLIENT_SECRET set
- [ ] MICROSOFT_CLIENT_TENANT_ID set
- [ ] ENABLE_OAUTH_SIGNUP=true
- [ ] ENABLE_OAUTH_GROUP_MANAGEMENT=true
- [ ] ENABLE_FORWARD_USER_INFO_HEADERS=true
- [ ] Redirect URI configured correctly

### Testing
- [ ] OAuth login works
- [ ] User created in Open WebUI
- [ ] Groups visible on user profile
- [ ] MCP tools filtered by group

---

## Need Help?

Contact Jacint for assistance with:
- MCP Proxy configuration
- Debugging OAuth issues
- Group mapping customization
