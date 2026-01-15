# OAuth Token Validation for MCP Proxy

**Date:** January 15, 2026
**Status:** Design Complete
**Author:** Jacint Alama

## Problem Statement

Current implementation passes user groups via HTTP headers (`X-OpenWebUI-User-Groups`). Lukas identified this as insecure because headers can be modified. We need a more secure, unified approach using OAuth token validation.

## Solution Overview

Instead of trusting headers, the MCP Proxy will validate the OAuth access token from Entra ID and extract user groups directly from the cryptographically signed token claims.

## Architecture

```
User (steve@highspring.com)
       │
       ▼
┌──────────────┐
│  Entra ID    │  ← User authenticates
│    OAuth     │
└──────┬───────┘
       │
       │  Access Token contains:
       │    - email: steve@highspring.com
       │    - groups: [Tenant-Google, Tenant-AcmeCorp]
       │    - aud, iss, exp (for validation)
       ▼
┌──────────────────────────────────────────────────────┐
│                   OPEN WEBUI                          │
│                                                       │
│  Passes token via: Authorization: Bearer <token>     │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                   MCP PROXY                           │
│                                                       │
│  1. Extract token from Authorization header           │
│  2. Fetch Entra ID public keys (cached)              │
│  3. Validate: signature, issuer, audience, expiry    │
│  4. Extract "groups" claim from validated token      │
│  5. Filter tools based on groups                     │
│                                                       │
│  Security: Token is signed by Microsoft              │
│            Cannot be faked or tampered               │
└──────────────────────────────────────────────────────┘
```

## Entra ID Configuration Required

### Step 1: Create App Registration for MCP Proxy

```
Azure Portal → Entra ID → App Registrations → New Registration

Name: "MCP Proxy API"
Supported account types: "Accounts in this organizational directory only (Highspring)"
```

### Step 2: Expose an API

```
App Registration → Expose an API → Add a scope

Scope name: mcp.tools.access
Who can consent: Admins and users
Display name: "Access MCP Tools"
```

### Step 3: Configure Token to Include Groups

```
App Registration → Token configuration → Add groups claim

Select: "Security groups"
Check: "Emit groups as role claims"
```

This makes tokens include:
```json
{
  "groups": ["<guid-for-Tenant-Google>", "<guid-for-Tenant-AcmeCorp>"]
}
```

### Step 4: Grant Open WebUI Permission

```
Open WebUI App Registration → API Permissions → Add permission
→ My APIs → MCP Proxy API → mcp.tools.access
→ Grant admin consent
```

## MCP Proxy Implementation

### New File: `token_validator.py`

```python
import os
import jwt
import httpx
from functools import lru_cache
from typing import Optional

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")

@lru_cache(maxsize=1)
def get_signing_keys():
    """Fetch Entra ID public keys for token validation (cached)."""
    url = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys"
    response = httpx.get(url)
    return response.json()["keys"]

def validate_token(token: str) -> dict:
    """
    Validate Entra ID token and extract claims.

    Returns:
        {
            "email": "steve@highspring.com",
            "groups": ["Tenant-Google", "Tenant-AcmeCorp"],
            "valid": True
        }

    Raises:
        jwt.InvalidTokenError: If token is invalid
    """
    keys = get_signing_keys()

    claims = jwt.decode(
        token,
        keys,
        algorithms=["RS256"],
        audience=AZURE_CLIENT_ID,
        issuer=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0"
    )

    return {
        "email": claims.get("preferred_username") or claims.get("email"),
        "groups": claims.get("groups", []),
        "valid": True
    }
```

### Updated: `mcp_server.py`

```python
from token_validator import validate_token

def get_user_info_from_context(ctx: Context) -> tuple[Optional[str], list[str]]:
    """
    Extract user info from OAuth token (secure) or fallback to headers.

    Priority:
    1. OAuth Token validation (preferred - cryptographically secure)
    2. Headers (fallback - for development/testing)
    """

    # Method 1: OAuth Token (PREFERRED)
    auth_header = get_auth_header_from_context(ctx)
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        try:
            claims = validate_token(token)
            log(f"[OAUTH] User: {claims['email']}, Groups: {claims['groups']}")
            return claims["email"], claims["groups"]
        except Exception as e:
            log(f"[OAUTH] Token validation failed: {e}")

    # Method 2: Headers (FALLBACK for dev/testing)
    log("[HEADERS] Falling back to header-based auth")
    return _get_user_from_headers(ctx)
```

## Environment Variables

```env
# MCP Proxy - Entra ID Token Validation
AZURE_TENANT_ID=<highspring-tenant-id>
AZURE_CLIENT_ID=<mcp-proxy-app-registration-id>

# Optional: For group GUID to name mapping
TENANT_GROUP_GOOGLE=<guid-for-Tenant-Google>
TENANT_GROUP_ACMECORP=<guid-for-Tenant-AcmeCorp>
TENANT_GROUP_MICROSOFT=<guid-for-Tenant-Microsoft>
```

## Security Comparison

| Aspect | Headers (Current) | OAuth Token (New) |
|--------|-------------------|-------------------|
| Can be faked? | Yes - anyone can set headers | No - signed by Microsoft |
| Validation | None - trust the value | Cryptographic signature check |
| Source of truth | Open WebUI passes it | Microsoft Entra ID |
| Production ready | No | Yes |

## Migration Path

1. **Phase 1 (Current):** Headers-based auth works for development
2. **Phase 2 (This Design):** Add OAuth token validation as primary method
3. **Phase 3 (Future):** Remove header fallback in production

## Dependencies

Add to `requirements.txt`:
```
PyJWT>=2.8.0
cryptography>=41.0.0
```

## Open Questions for Lukas

1. Should we map group GUIDs to friendly names (Tenant-Google) in MCP Proxy config, or use GUIDs directly?
2. Should header fallback be disabled in production?
3. Does Open WebUI need configuration to pass the access token to MCP servers?

## References

- [Secure MCP Server with OAuth and Entra ID](https://damienbod.com/2025/09/23/implement-a-secure-mcp-server-using-oauth-and-entra-id/)
- [Open WebUI SSO Docs](https://docs.openwebui.com/features/auth/sso/)
- [Per-User MCP Authentication Discussion](https://github.com/open-webui/open-webui/discussions/14121)
- [MCPO OAuth Guide](https://github.com/open-webui/mcpo/blob/main/OAUTH_GUIDE.md)
