# OAuth Token Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OAuth token validation to MCP Proxy so user groups are extracted from cryptographically signed Entra ID tokens instead of headers.

**Architecture:** MCP Proxy receives Authorization Bearer token from Open WebUI, validates it against Entra ID public keys, extracts groups claim, and filters tools accordingly. Falls back to headers if token not present (for dev/testing).

**Tech Stack:** Python, FastMCP, PyJWT, httpx, Entra ID / Microsoft Identity

---

## Task 1: Add Dependencies

**Files:**
- Modify: `mcp-proxy/requirements.txt`

**Step 1: Add JWT and cryptography packages**

Add these lines to `mcp-proxy/requirements.txt`:

```
PyJWT>=2.8.0
cryptography>=41.0.0
```

**Step 2: Verify file**

Run: `cat mcp-proxy/requirements.txt | grep -E "(PyJWT|cryptography)"`
Expected: Both packages listed

**Step 3: Commit**

```bash
git add mcp-proxy/requirements.txt
git commit -m "chore: add PyJWT and cryptography dependencies for OAuth validation"
```

---

## Task 2: Create Token Validator Module

**Files:**
- Create: `mcp-proxy/token_validator.py`

**Step 1: Create the token validator module**

Create `mcp-proxy/token_validator.py`:

```python
"""
Token Validator for Entra ID OAuth tokens.

Validates JWT tokens from Microsoft Entra ID and extracts user claims
including email and group memberships.
"""

import os
import jwt
import httpx
from functools import lru_cache
from typing import Optional
from jwt import PyJWKClient

# Configuration from environment
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")

# Entra ID endpoints
JWKS_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys"
ISSUER = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0"

# Group GUID to name mapping (optional - for friendly names)
GROUP_MAPPINGS = {
    os.getenv("TENANT_GROUP_GOOGLE_GUID", ""): "Tenant-Google",
    os.getenv("TENANT_GROUP_ACMECORP_GUID", ""): "Tenant-AcmeCorp",
    os.getenv("TENANT_GROUP_MICROSOFT_GUID", ""): "Tenant-Microsoft",
}


def log(msg: str):
    """Debug logging."""
    print(f"[TOKEN-VALIDATOR] {msg}")


@lru_cache(maxsize=1)
def get_jwk_client() -> Optional[PyJWKClient]:
    """
    Get cached JWK client for token validation.
    Returns None if AZURE_TENANT_ID is not configured.
    """
    if not AZURE_TENANT_ID:
        log("AZURE_TENANT_ID not configured - OAuth validation disabled")
        return None

    try:
        return PyJWKClient(JWKS_URL)
    except Exception as e:
        log(f"Failed to create JWK client: {e}")
        return None


def map_group_guids_to_names(group_guids: list[str]) -> list[str]:
    """
    Map Entra ID group GUIDs to friendly names.
    If no mapping exists, returns the GUID as-is.
    """
    result = []
    for guid in group_guids:
        name = GROUP_MAPPINGS.get(guid)
        if name:
            result.append(name)
        else:
            # Keep GUID if no mapping (allows direct GUID-based config)
            result.append(guid)
    return result


def validate_token(token: str) -> dict:
    """
    Validate Entra ID access token and extract claims.

    Args:
        token: JWT access token from Authorization header

    Returns:
        {
            "email": "steve@highspring.com",
            "groups": ["Tenant-Google", "Tenant-AcmeCorp"],
            "valid": True
        }

    Raises:
        ValueError: If token validation fails or required config missing
        jwt.InvalidTokenError: If token is invalid/expired/wrong audience
    """
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        raise ValueError("AZURE_TENANT_ID and AZURE_CLIENT_ID must be configured")

    jwk_client = get_jwk_client()
    if not jwk_client:
        raise ValueError("Failed to initialize JWK client")

    # Get signing key from token header
    signing_key = jwk_client.get_signing_key_from_jwt(token)

    # Decode and validate token
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=AZURE_CLIENT_ID,
        issuer=ISSUER,
        options={"verify_exp": True}
    )

    # Extract email (try multiple claim names)
    email = (
        claims.get("preferred_username") or
        claims.get("email") or
        claims.get("upn") or
        claims.get("unique_name")
    )

    # Extract groups and map to friendly names
    group_guids = claims.get("groups", [])
    groups = map_group_guids_to_names(group_guids)

    log(f"Token validated - Email: {email}, Groups: {groups}")

    return {
        "email": email,
        "groups": groups,
        "valid": True
    }


def is_oauth_configured() -> bool:
    """Check if OAuth validation is properly configured."""
    return bool(AZURE_TENANT_ID and AZURE_CLIENT_ID)
```

**Step 2: Verify file created**

Run: `ls -la mcp-proxy/token_validator.py`
Expected: File exists

**Step 3: Commit**

```bash
git add mcp-proxy/token_validator.py
git commit -m "feat: add token_validator module for Entra ID OAuth validation"
```

---

## Task 3: Update MCP Server to Use Token Validation

**Files:**
- Modify: `mcp-proxy/mcp_server.py`

**Step 1: Add import for token validator**

At the top of `mcp-proxy/mcp_server.py`, after existing imports, add:

```python
from token_validator import validate_token, is_oauth_configured
```

**Step 2: Add helper function to extract Authorization header**

Add this function after `get_user_info_from_context`:

```python
def get_auth_header_from_context(ctx: Context) -> Optional[str]:
    """Extract Authorization header from MCP context."""
    if hasattr(ctx, 'request_context') and ctx.request_context:
        request = getattr(ctx.request_context, 'request', None)
        if request:
            headers = getattr(request, 'headers', None)
            if headers and hasattr(headers, 'get'):
                return headers.get('Authorization') or headers.get('authorization')
    return None
```

**Step 3: Update get_user_info_from_context to try OAuth first**

Replace the beginning of `get_user_info_from_context` function:

```python
def get_user_info_from_context(ctx: Context) -> tuple[Optional[str], list[str]]:
    """
    Extract user email and groups from MCP context.

    Priority:
    1. OAuth Token validation (secure - cryptographically signed)
    2. Headers (fallback - for development/testing)

    Returns:
        Tuple of (email, groups_list)
    """
    user_email = None
    user_groups = []

    # Method 1: OAuth Token Validation (PREFERRED - Secure)
    if is_oauth_configured():
        auth_header = get_auth_header_from_context(ctx)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            try:
                claims = validate_token(token)
                log(f"[OAUTH] Validated user: {claims['email']}, groups: {claims['groups']}")
                return claims["email"], claims["groups"]
            except Exception as e:
                log(f"[OAUTH] Token validation failed: {e} - falling back to headers")

    # Method 2: Headers (FALLBACK - for dev/testing)
    log("[HEADERS] Using header-based authentication")

    # ... rest of existing header code ...
```

**Step 4: Verify changes**

Run: `grep -n "validate_token\|is_oauth_configured\|OAUTH" mcp-proxy/mcp_server.py`
Expected: Shows the new OAuth-related code

**Step 5: Commit**

```bash
git add mcp-proxy/mcp_server.py
git commit -m "feat: integrate OAuth token validation into MCP server"
```

---

## Task 4: Update Dockerfile with New Dependencies

**Files:**
- Modify: `mcp-proxy/Dockerfile`

**Step 1: Verify requirements.txt is copied and installed**

The existing Dockerfile should already have:
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

No changes needed if this exists.

**Step 2: Verify**

Run: `grep -A1 "requirements.txt" mcp-proxy/Dockerfile`
Expected: Shows COPY and RUN pip install

---

## Task 5: Add Environment Variables to Kubernetes Deployment

**Files:**
- Modify: `kubernetes/mcp-proxy-deployment.yaml`

**Step 1: Add Entra ID environment variables**

Add these environment variables to the mcp-proxy container spec:

```yaml
- name: AZURE_TENANT_ID
  valueFrom:
    secretKeyRef:
      name: mcp-secrets
      key: azure-tenant-id
      optional: true
- name: AZURE_CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: mcp-secrets
      key: azure-client-id
      optional: true
- name: TENANT_GROUP_GOOGLE_GUID
  valueFrom:
    secretKeyRef:
      name: mcp-secrets
      key: tenant-group-google-guid
      optional: true
- name: TENANT_GROUP_ACMECORP_GUID
  valueFrom:
    secretKeyRef:
      name: mcp-secrets
      key: tenant-group-acmecorp-guid
      optional: true
```

**Step 2: Commit**

```bash
git add kubernetes/mcp-proxy-deployment.yaml
git commit -m "feat: add Entra ID OAuth env vars to MCP Proxy deployment"
```

---

## Task 6: Update Secrets Template

**Files:**
- Modify: `kubernetes/secrets-template.yaml`

**Step 1: Add new secret keys**

Add these keys to the secrets template:

```yaml
# Entra ID OAuth Configuration (for MCP Proxy token validation)
azure-tenant-id: ""           # Highspring tenant ID
azure-client-id: ""           # MCP Proxy app registration ID
tenant-group-google-guid: ""  # GUID for Tenant-Google group
tenant-group-acmecorp-guid: "" # GUID for Tenant-AcmeCorp group
```

**Step 2: Commit**

```bash
git add kubernetes/secrets-template.yaml
git commit -m "docs: add Entra ID OAuth secrets to template"
```

---

## Task 7: Build and Test Locally

**Step 1: Build new Docker image**

Run:
```bash
cd mcp-proxy
docker build -t mcp-proxy:v8-oauth .
```

Expected: Build succeeds

**Step 2: Test without OAuth config (should fallback to headers)**

Run:
```bash
docker run --rm -p 8001:8001 mcp-proxy:v8-oauth
```

In another terminal:
```bash
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -H "X-OpenWebUI-User-Email: test@highspring.com" \
  -H "X-OpenWebUI-User-Groups: Tenant-Google" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}'
```

Expected: Server responds, logs show `[HEADERS] Using header-based authentication`

**Step 3: Commit all changes**

```bash
git add .
git commit -m "feat: complete OAuth token validation implementation"
```

---

## Task 8: Deploy to Kubernetes

**Step 1: Deploy new image**

Run:
```bash
kubectl set image deployment/mcp-proxy mcp-proxy=mcp-proxy:v8-oauth -n open-webui
kubectl rollout status deployment/mcp-proxy -n open-webui
```

Expected: Deployment successful

**Step 2: Verify logs show OAuth check**

Run:
```bash
kubectl logs -l app=mcp-proxy -n open-webui --tail=20 | grep -E "(OAUTH|TOKEN)"
```

Expected: Shows OAuth-related log messages

---

## Summary

After completing all tasks:

1. ✅ MCP Proxy can validate Entra ID OAuth tokens
2. ✅ Groups extracted from signed token claims (secure)
3. ✅ Falls back to headers when OAuth not configured (dev/testing)
4. ✅ Ready for Lukas to configure Entra ID app registration

**To enable OAuth in production:**
1. Lukas creates MCP Proxy app registration in Entra ID
2. Lukas configures groups claim in token
3. Add secrets: `azure-tenant-id`, `azure-client-id`, group GUIDs
4. Redeploy - OAuth validation activates automatically
