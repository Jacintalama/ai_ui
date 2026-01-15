"""
Token Validator for Microsoft OAuth tokens.

Validates JWT tokens from Microsoft Identity Platform (including 'consumers' tenant
for personal Microsoft accounts) and extracts user email.

Note: Personal accounts (consumers) do NOT have groups. Tenant access is looked up
from the database instead.
"""

import os
import jwt
from functools import lru_cache
from typing import Optional
from jwt import PyJWKClient

# Configuration from environment (matches Open WebUI's Microsoft OAuth config)
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_CLIENT_TENANT_ID", "consumers")

# For 'consumers' tenant, Microsoft uses a fixed issuer GUID
# See: https://learn.microsoft.com/en-us/entra/identity-platform/id-tokens
CONSUMERS_ISSUER_GUID = "9188040d-6c67-4c5b-b112-36a304b66dad"

# Endpoints based on tenant
if MICROSOFT_TENANT_ID == "consumers":
    JWKS_URL = "https://login.microsoftonline.com/consumers/discovery/v2.0/keys"
    # Consumers uses a fixed GUID as issuer
    ISSUER = f"https://login.microsoftonline.com/{CONSUMERS_ISSUER_GUID}/v2.0"
elif MICROSOFT_TENANT_ID == "common":
    JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
    ISSUER = None  # Common tenant has multiple possible issuers
else:
    # Organizational tenant (specific tenant ID)
    JWKS_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/discovery/v2.0/keys"
    ISSUER = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/v2.0"


def log(msg: str):
    """Debug logging."""
    print(f"[TOKEN-VALIDATOR] {msg}")


# Log configuration at startup
log(f"Microsoft OAuth Config:")
log(f"  Client ID: {MICROSOFT_CLIENT_ID[:8]}..." if MICROSOFT_CLIENT_ID else "  Client ID: NOT SET")
log(f"  Tenant: {MICROSOFT_TENANT_ID}")
log(f"  JWKS URL: {JWKS_URL}")
log(f"  Issuer: {ISSUER}")


_jwk_client: Optional[PyJWKClient] = None


def get_jwk_client() -> Optional[PyJWKClient]:
    """
    Get cached JWK client for token validation.
    Returns None if MICROSOFT_CLIENT_ID is not configured.
    """
    global _jwk_client

    if not MICROSOFT_CLIENT_ID:
        log("MICROSOFT_CLIENT_ID not configured - OAuth validation disabled")
        return None

    if _jwk_client is None:
        try:
            log(f"Creating JWK client for {JWKS_URL}")
            _jwk_client = PyJWKClient(JWKS_URL)
            log("JWK client created successfully")
        except Exception as e:
            log(f"Failed to create JWK client: {e}")
            return None

    return _jwk_client


def validate_token(token: str) -> dict:
    """
    Validate Microsoft OAuth access token and extract email.

    Args:
        token: JWT access token from Authorization header

    Returns:
        {
            "email": "user@outlook.com",
            "valid": True
        }

    Note: Groups are NOT returned - use database lookup for tenant access.

    Raises:
        ValueError: If token validation fails or required config missing
        jwt.InvalidTokenError: If token is invalid/expired/wrong audience
    """
    if not MICROSOFT_CLIENT_ID:
        raise ValueError("MICROSOFT_CLIENT_ID must be configured")

    jwk_client = get_jwk_client()
    if not jwk_client:
        raise ValueError("Failed to initialize JWK client")

    try:
        # Get signing key from token header
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        # Decode and validate token
        decode_options = {"verify_exp": True}

        # For 'common' tenant, skip issuer validation (multiple possible issuers)
        if ISSUER is None:
            decode_options["verify_iss"] = False
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=MICROSOFT_CLIENT_ID,
                options=decode_options
            )
        else:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=MICROSOFT_CLIENT_ID,
                issuer=ISSUER,
                options=decode_options
            )

        # Extract email (try multiple claim names)
        # For personal accounts: preferred_username is usually the email
        email = (
            claims.get("preferred_username") or
            claims.get("email") or
            claims.get("upn") or
            claims.get("unique_name")
        )

        if not email:
            log(f"Warning: No email found in token claims: {list(claims.keys())}")

        log(f"Token validated - Email: {email}")

        return {
            "email": email,
            "valid": True
        }

    except jwt.ExpiredSignatureError:
        log("Token has expired")
        raise ValueError("Token has expired")
    except jwt.InvalidAudienceError:
        log(f"Invalid audience - expected {MICROSOFT_CLIENT_ID}")
        raise ValueError("Invalid token audience")
    except jwt.InvalidIssuerError as e:
        log(f"Invalid issuer: {e}")
        raise ValueError("Invalid token issuer")
    except Exception as e:
        log(f"Token validation failed: {e}")
        raise


def is_oauth_configured() -> bool:
    """Check if OAuth validation is properly configured."""
    return bool(MICROSOFT_CLIENT_ID)


def get_token_info(token: str) -> dict:
    """
    Decode token without validation to inspect claims (for debugging).

    WARNING: Do not use this for authentication - use validate_token() instead.
    """
    try:
        # Decode without verification (just to see claims)
        claims = jwt.decode(token, options={"verify_signature": False})
        return {
            "email": claims.get("preferred_username") or claims.get("email"),
            "iss": claims.get("iss"),
            "aud": claims.get("aud"),
            "exp": claims.get("exp"),
            "claims": list(claims.keys())
        }
    except Exception as e:
        return {"error": str(e)}
