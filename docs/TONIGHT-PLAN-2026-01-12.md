# Tonight's Plan - January 12, 2026

## Goal
Set up Microsoft Entra ID OAuth for automatic multi-tenant MCP access control.

---

## Timeline

### Phase 1: Lukas Sets Up Entra ID (30 mins)
**Who:** Lukas
**Where:** Azure Portal (https://portal.azure.com)

| Step | Task | Time |
|------|------|------|
| 1.1 | Create App Registration | 5 min |
| 1.2 | Copy Client ID, Tenant ID | 1 min |
| 1.3 | Create Client Secret | 2 min |
| 1.4 | Add API Permissions | 5 min |
| 1.5 | Grant Admin Consent | 1 min |
| 1.6 | Configure Token Claims (groups) | 5 min |
| 1.7 | Create Security Groups | 10 min |

**Output:**
- Client ID: `________________________________`
- Client Secret: `________________________________`
- Tenant ID: `________________________________`

---

### Phase 2: Configure Open WebUI (15 mins)
**Who:** Jacint (with Lukas's credentials)
**Where:** Deployment configuration

| Step | Task |
|------|------|
| 2.1 | Add MICROSOFT_CLIENT_ID to env |
| 2.2 | Add MICROSOFT_CLIENT_SECRET to env |
| 2.3 | Add MICROSOFT_CLIENT_TENANT_ID to env |
| 2.4 | Enable OAuth settings |
| 2.5 | Redeploy/restart Open WebUI |

---

### Phase 3: Testing (15 mins)
**Who:** Both

| Test | Expected Result |
|------|-----------------|
| 3.1 | "Sign in with Microsoft" button visible | ✅ |
| 3.2 | OAuth login works | ✅ |
| 3.3 | User created in Open WebUI | ✅ |
| 3.4 | Groups synced from Entra ID | ✅ |
| 3.5 | MCP tools filtered by group | ✅ |

---

## Checklist

### Entra ID Setup (Lukas)
- [ ] App Registration created
- [ ] Client ID copied
- [ ] Client Secret created
- [ ] Tenant ID copied
- [ ] API Permissions: User.Read, email, openid, profile
- [ ] API Permission: GroupMember.Read.All
- [ ] Admin Consent granted
- [ ] Groups created: MCP-GitHub, MCP-Admin
- [ ] Test user added to MCP-GitHub group

### Open WebUI Config (Jacint)
- [ ] MICROSOFT_CLIENT_ID set
- [ ] MICROSOFT_CLIENT_SECRET set
- [ ] MICROSOFT_CLIENT_TENANT_ID set
- [ ] ENABLE_OAUTH_SIGNUP=true
- [ ] ENABLE_OAUTH_GROUP_MANAGEMENT=true
- [ ] ENABLE_FORWARD_USER_INFO_HEADERS=true
- [ ] Service restarted

### Testing
- [ ] OAuth login successful
- [ ] User appears in Admin Panel
- [ ] Groups visible on user
- [ ] MCP tools filtered correctly

---

## Files to Reference

| File | Purpose |
|------|---------|
| `QUICK-REFERENCE-entra-id-setup.md` | One-page guide for Lukas |
| `SETUP-GUIDE-oauth-multi-tenant.md` | Detailed step-by-step |
| `microsoft-entra-id-free-tier.md` | Free tier info |

---

## Redirect URI (IMPORTANT!)

Must be set EXACTLY as:
```
https://ai-ui.coolestdomain.win/oauth/microsoft/callback
```

---

## After Tonight

Once OAuth is working:
1. ✅ Users can login with Microsoft
2. ✅ Groups auto-sync from Entra ID
3. ✅ MCP tools filtered by group membership
4. ✅ Ready for 15,000 users!

---

## Contact

**Jacint:** Ready to help with configuration
**Lukas:** Setting up Entra ID tonight
