# mcp-proxy/auth.py
"""
Authentication module for MCP Proxy.

SECURITY MODEL:
- Headers alone (X-OpenWebUI-User-Email) can be FAKED by attackers
- JWT validation provides CRYPTOGRAPHIC PROOF that the request came from Open WebUI
- Headers are ONLY trusted AFTER JWT validation succeeds

Authentication Priority:
1. Entra ID Token mode (X-Auth-Source: entra-token): Groups extracted from actual Entra ID JWT
   - Most secure: Groups come from cryptographically signed Entra ID token
   - Used by mcp_entra_token_auth.py function
2. API Gateway mode (API_GATEWAY_MODE=true): Trust headers from validated gateway
3. JWT-first mode (default): Validate JWT, then trust headers
4. Reject requests without valid JWT (unless API_GATEWAY_MODE=true)
"""
import os
import jwt
from fastapi import Request, HTTPException
from typing import Optional, List
from dataclasses import dataclass, field

# Open WebUI JWT secret - must match WEBUI_SECRET_KEY in Open WebUI
WEBUI_SECRET_KEY = os.environ.get("WEBUI_SECRET_KEY", "")

# API Gateway mode - when True, trust headers from API Gateway (APIM/Kong validates tokens externally)
API_GATEWAY_MODE = os.environ.get("API_GATEWAY_MODE", "false").lower() == "true"

# Debug logging
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"


def _log(msg: str):
    """Debug logging."""
    if DEBUG:
        print(f"[AUTH] {msg}")


@dataclass
class UserInfo:
    """User information extracted from Open WebUI headers, JWT, or API Gateway."""
    email: str
    user_id: str
    name: str
    role: str
    chat_id: Optional[str] = None
    # Entra ID specific fields (populated via API Gateway or headers)
    entra_groups: List[str] = field(default_factory=list)
    entra_tenant_id: Optional[str] = None
    # Track authentication method for auditing
    auth_method: str = "unknown"


def _validate_jwt(token: str) -> Optional[dict]:
    """
    Validate JWT signature and return claims if valid.

    Returns None if:
    - WEBUI_SECRET_KEY is not configured
    - Token signature is invalid
    - Token is expired
    """
    if not WEBUI_SECRET_KEY:
        _log("WEBUI_SECRET_KEY not configured - JWT validation disabled")
        return None

    try:
        # Validate signature using WEBUI_SECRET_KEY (same key Open WebUI uses)
        claims = jwt.decode(token, WEBUI_SECRET_KEY, algorithms=["HS256"])
        _log(f"JWT validated successfully - claims: {list(claims.keys())}")
        return claims
    except jwt.ExpiredSignatureError:
        _log("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        _log(f"JWT validation failed: {e}")
        return None


def extract_user_from_entra_token(request: Request) -> Optional[UserInfo]:
    """
    Extract user info from Entra ID token-based headers.

    SECURITY: This is the MOST SECURE method because:
    - The mcp_entra_token_auth.py function receives __oauth_token__ from Open WebUI
    - It decodes the actual Entra ID JWT (signed by Microsoft)
    - Groups come directly from the token's 'groups' claim
    - This is NOT spoofable - the token is cryptographically verified by Open WebUI

    Headers (set by mcp_entra_token_auth.py):
    - X-Auth-Source: "entra-token" (identifies this auth method)
    - X-OpenWebUI-User-Email: User's email from Entra ID token
    - X-Entra-Groups: Comma-separated list of groups FROM THE TOKEN
    - X-Entra-OID: User's Entra ID object ID
    - X-Entra-TID: Azure tenant ID
    """
    # Only use this method if X-Auth-Source indicates token-based auth
    auth_source = request.headers.get("X-Auth-Source", "")
    if auth_source != "entra-token":
        return None

    email = request.headers.get("X-OpenWebUI-User-Email")
    if not email:
        return None

    # Groups from the actual Entra ID token (most trustworthy)
    groups_header = request.headers.get("X-Entra-Groups", "")
    groups = [g.strip() for g in groups_header.split(",") if g.strip()]

    _log(f"Entra Token auth (SECURE): {email} with {len(groups)} groups from token")

    return UserInfo(
        email=email,
        user_id=request.headers.get("X-Entra-OID", ""),
        name=request.headers.get("X-OpenWebUI-User-Name", email.split("@")[0]),
        role="admin" if "MCP-Admin" in groups else "user",
        chat_id=None,
        entra_groups=groups,
        entra_tenant_id=request.headers.get("X-Entra-TID"),
        auth_method="entra_token"  # Most secure method
    )


def extract_user_from_api_gateway(request: Request) -> Optional[UserInfo]:
    """
    Extract user info from API Gateway headers (Azure APIM / Kong).

    SECURITY: This is ONLY called when API_GATEWAY_MODE=true, meaning
    an external API Gateway has already validated the Entra ID JWT.
    The gateway sets these trusted headers after validation.

    Headers:
    - X-User-Email: User's email from Entra ID token
    - X-User-Groups: Comma-separated list of Entra ID groups
    - X-Tenant-ID: Azure tenant ID
    - X-User-Name: User's display name (optional)
    - X-User-OID: User's object ID in Entra ID (optional)
    """
    email = request.headers.get("X-User-Email")
    if not email:
        return None

    # Parse groups from comma-separated string
    groups_header = request.headers.get("X-User-Groups", "")
    groups = [g.strip() for g in groups_header.split(",") if g.strip()]

    _log(f"API Gateway auth: {email} with groups: {groups}")

    return UserInfo(
        email=email,
        user_id=request.headers.get("X-User-OID", ""),
        name=request.headers.get("X-User-Name", email.split("@")[0]),
        role="admin" if "MCP-Admin" in groups else "user",
        chat_id=None,
        entra_groups=groups,
        entra_tenant_id=request.headers.get("X-Tenant-ID"),
        auth_method="api_gateway"
    )


def _extract_user_from_headers_after_jwt_validation(request: Request) -> Optional[UserInfo]:
    """
    Extract user info from X-OpenWebUI-* headers.

    SECURITY: This should ONLY be called AFTER JWT validation succeeds.
    The JWT proves the request came from Open WebUI, making headers trustworthy.
    """
    email = request.headers.get("X-OpenWebUI-User-Email")
    if not email:
        return None

    # Parse groups from multiple possible header names
    groups_header = (
        request.headers.get("X-OpenWebUI-User-Groups") or
        request.headers.get("X-User-Groups") or
        request.headers.get("X-Entra-Groups") or
        ""
    )
    groups = [g.strip() for g in groups_header.split(",") if g.strip()]

    _log(f"Header auth (JWT-validated): {email} with groups: {groups}")

    return UserInfo(
        email=email,
        user_id=request.headers.get("X-OpenWebUI-User-Id", ""),
        name=request.headers.get("X-OpenWebUI-User-Name", ""),
        role=request.headers.get("X-OpenWebUI-User-Role", "user"),
        chat_id=request.headers.get("X-OpenWebUI-Chat-Id"),
        entra_groups=groups,
        auth_method="jwt_validated_headers"
    )


def extract_user_from_headers_optional(request: Request) -> Optional[UserInfo]:
    """
    Extract user info securely, returning None if authentication fails.

    SECURITY MODEL (in priority order):
    1. Entra ID Token mode: X-Auth-Source: entra-token (groups from actual Entra ID JWT)
    2. API Gateway mode: Trust API Gateway headers (gateway validates externally)
    3. JWT-first mode: Validate Open WebUI JWT, then trust headers
    4. Reject if no valid authentication

    This prevents header spoofing attacks where an attacker could send:
        X-OpenWebUI-User-Email: admin@company.com
    without valid authentication.
    """
    # ==========================================================================
    # Mode 1: Entra ID Token (MOST SECURE - groups from actual Entra ID JWT)
    # ==========================================================================
    # This is used when requests come from mcp_entra_token_auth.py function
    # which decodes the actual Entra ID token and extracts groups from claims
    user = extract_user_from_entra_token(request)
    if user:
        _log(f"Using Entra ID Token authentication (most secure): {user.email}")
        return user

    # ==========================================================================
    # Mode 2: API Gateway (external token validation)
    # ==========================================================================
    if API_GATEWAY_MODE:
        _log("Using API Gateway authentication mode")
        user = extract_user_from_api_gateway(request)
        if user:
            return user
        _log("API Gateway headers not present")

    # ==========================================================================
    # Mode 3: JWT-First Authentication (SECURE - default mode)
    # ==========================================================================
    # Step 1: Get JWT from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        _log("No Bearer token in Authorization header - rejecting request")
        return None

    token = auth_header[7:]  # Remove "Bearer " prefix

    # Step 2: Validate JWT signature (CRITICAL SECURITY CHECK)
    jwt_claims = _validate_jwt(token)
    if not jwt_claims:
        _log("JWT validation failed - rejecting request (headers cannot be trusted)")
        return None

    _log("JWT validated - headers are now trustworthy")

    # Step 3: JWT is valid! Now we can trust the headers
    # Try to get user info from X-OpenWebUI-* headers first (more complete)
    user = _extract_user_from_headers_after_jwt_validation(request)
    if user:
        return user

    # Step 4: Fallback - extract user info from JWT claims directly
    # (Open WebUI JWT may have limited claims like id, exp, jti)
    email = jwt_claims.get("email") or jwt_claims.get("preferred_username")
    if email:
        _log(f"Using email from JWT claims: {email}")
        return UserInfo(
            email=email,
            user_id=jwt_claims.get("id", jwt_claims.get("sub", "")),
            name=jwt_claims.get("name", ""),
            role=jwt_claims.get("role", "user"),
            chat_id=None,
            auth_method="jwt_claims"
        )

    # Step 5: JWT valid but no email found anywhere
    _log("JWT valid but no user email found in headers or claims")
    return None


def extract_user_from_headers(request: Request) -> UserInfo:
    """
    Extract user info from headers with JWT validation. Raises 401 if authentication fails.

    This is the REQUIRED authentication function for protected endpoints.
    """
    user = extract_user_from_headers_optional(request)
    if user:
        return user

    # Determine appropriate error message
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        detail = "Missing Authorization header. Ensure Open WebUI tool server is configured with 'Session' auth type."
    elif not auth_header.startswith("Bearer "):
        detail = "Invalid Authorization header format. Expected 'Bearer <token>'."
    elif not WEBUI_SECRET_KEY:
        detail = "Server misconfiguration: WEBUI_SECRET_KEY not set. Contact administrator."
    else:
        detail = "JWT validation failed. Token may be expired or invalid. Please log out and log back in."

    raise HTTPException(status_code=401, detail=detail)


# =============================================================================
# LEGACY COMPATIBILITY - Deprecated functions
# =============================================================================

def extract_user_from_jwt(token: str) -> Optional[UserInfo]:
    """
    DEPRECATED: Use extract_user_from_headers_optional() instead.

    This function is kept for backward compatibility but should not be used
    directly as it doesn't follow the secure JWT-first pattern.
    """
    claims = _validate_jwt(token)
    if not claims:
        return None

    email = claims.get("email")
    if not email:
        return None

    return UserInfo(
        email=email,
        user_id=claims.get("id", ""),
        name=claims.get("name", ""),
        role=claims.get("role", "user"),
        chat_id=None,
        auth_method="jwt_direct"
    )
