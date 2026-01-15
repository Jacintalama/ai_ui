# Microsoft Entra ID - FREE Tier Information

**Date:** January 12, 2026
**Status:** Ready for Lukas to set up

---

## Summary

Microsoft Entra ID has a **FREE tier** that supports OAuth and group management - enough for our multi-tenant MCP setup.

---

## What's Included in FREE Tier

| Feature | Free Tier | Paid (P1/P2) |
|---------|-----------|--------------|
| User & Group Management | ✅ Up to 500,000 objects | ✅ |
| Single Sign-On (SSO) | ✅ Basic | ✅ Advanced |
| Multi-Factor Auth (MFA) | ✅ Security defaults | ✅ Conditional |
| OAuth 2.0 / OpenID Connect | ✅ Full support | ✅ |
| App Registration | ✅ Unlimited | ✅ |
| Group-based access | ✅ Supported | ✅ |
| Price | **FREE** | $6-$9/user/month |

---

## How to Get It

### Option 1: Azure Account (Lukas has this!)

If you have an Azure account, Entra ID Free is **automatically included**:

1. Go to https://portal.azure.com
2. Search for "Microsoft Entra ID" (formerly Azure AD)
3. You already have it!

### Option 2: Microsoft 365 Developer Program

For testing with full E5 features:

1. Go to: https://aka.ms/o365devprogram
2. Click **"Join now"**
3. Get 25 E5 licenses for 90 days (renewable)

---

## What We Need for Multi-Tenant MCP

From Entra ID, we need:

1. **App Registration** - To get Client ID and Secret
2. **Security Groups** - MCP-GitHub, MCP-Google, MCP-Microsoft, MCP-Admin
3. **User Assignment** - Add users to appropriate groups

### Groups to Create

| Group Name | MCP Access |
|------------|------------|
| `MCP-GitHub` | GitHub tools (26 tools) |
| `MCP-Filesystem` | Filesystem tools (14 tools) |
| `MCP-Google` | Google tenant |
| `MCP-Microsoft` | Microsoft tenant |
| `MCP-Admin` | ALL tools (full access) |

---

## Limitations of Free Tier

What's **NOT** included (but we don't need these):

- ❌ Conditional Access policies
- ❌ Privileged Identity Management
- ❌ Access Reviews automation
- ❌ Identity Protection

**These are NOT required for our OAuth + Group sync setup.**

---

## Sources

- [Microsoft Entra ID Free - Microsoft Learn](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/microsoft-entra-id-free)
- [Create a free Microsoft Entra developer tenant](https://learn.microsoft.com/en-us/entra/verified-id/how-to-create-a-free-developer-account)
- [Microsoft Entra Plans and Pricing](https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing)
- [Features and Limitations of Free Tier](https://nexetic.com/features-and-limitations-of-free-tier-in-microsoft-entra-id/)
