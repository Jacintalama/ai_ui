"""
MCP Auth Proxy — API-key authentication gateway for external MCP access.

Validates Bearer API keys against PostgreSQL, then proxies authenticated
requests to the internal MCP proxy with user identity headers.
"""

import hashlib
import logging
import os
import re
import secrets

import asyncpg
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MCP_PROXY_URL = os.environ.get("MCP_PROXY_URL", "http://mcp-proxy:8000")
MCP_PROXY_MCP_URL = os.environ.get("MCP_PROXY_MCP_URL", "http://mcp-proxy:8001")
ADMIN_SECRET = os.environ.get("MCP_AUTH_ADMIN_SECRET", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-auth")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="MCP Auth Proxy", version="1.0.0")

# Global connection pool (initialised at startup)
pool: asyncpg.Pool | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup() -> None:
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        logger.info("Connected to PostgreSQL")
    except Exception:
        logger.exception("Failed to connect to PostgreSQL")
        raise

    # Ensure the api-keys table exists
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_api_keys (
                id            SERIAL PRIMARY KEY,
                api_key_hash  TEXT UNIQUE NOT NULL,
                user_email    TEXT NOT NULL,
                user_groups   TEXT NOT NULL DEFAULT '',
                label         TEXT NOT NULL DEFAULT '',
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        logger.info("mcp_api_keys table ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    global pool
    if pool:
        await pool.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _generate_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> JSONResponse:
    if pool is None:
        return JSONResponse({"status": "unhealthy"}, status_code=503)
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        return JSONResponse({"status": "unhealthy"}, status_code=503)
    return JSONResponse({"status": "ok", "service": "mcp-auth"})


# ---------------------------------------------------------------------------
# Admin: generate a new API key
# ---------------------------------------------------------------------------
@app.post("/admin/generate-key")
async def generate_key(request: Request) -> JSONResponse:
    # Admin endpoint requires MCP_AUTH_ADMIN_SECRET header
    admin_token = request.headers.get("x-admin-secret", "")
    if not ADMIN_SECRET or not secrets.compare_digest(admin_token, ADMIN_SECRET):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    if pool is None:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    user_email = body.get("user_email", "")
    user_groups = body.get("user_groups", "")
    label = body.get("label", "")

    if not user_email:
        return JSONResponse({"error": "user_email is required"}, status_code=400)

    raw_key = _generate_key()
    key_hash = _hash_key(raw_key)

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mcp_api_keys (api_key_hash, user_email, user_groups, label)
                VALUES ($1, $2, $3, $4)
                """,
                key_hash,
                user_email,
                user_groups,
                label,
            )
    except Exception:
        logger.exception("Failed to insert API key")
        return JSONResponse({"error": "Database error"}, status_code=500)

    return JSONResponse(
        {
            "api_key": raw_key,
            "user_email": user_email,
            "user_groups": user_groups,
            "label": label,
            "message": "Store this key securely — it cannot be retrieved later.",
        },
        status_code=201,
    )


# ---------------------------------------------------------------------------
# Catch-all proxy
# ---------------------------------------------------------------------------
def _sanitize_header(value: str) -> str:
    """Strip control characters to prevent header injection."""
    return re.sub(r"[\r\n\x00]", "", value)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str):
    if pool is None:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    # --- Extract & validate Bearer token ---
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)

    api_key = auth_header.split(None, 1)[1].strip() if " " in auth_header else ""
    if not api_key:
        return JSONResponse({"error": "Empty API key"}, status_code=401)

    key_hash = _hash_key(api_key)

    # --- Lookup in DB ---
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_email, user_groups FROM mcp_api_keys WHERE api_key_hash = $1",
                key_hash,
            )
    except Exception:
        logger.exception("Database lookup failed")
        return JSONResponse({"error": "Internal server error"}, status_code=500)

    if row is None:
        return JSONResponse({"error": "Invalid API key"}, status_code=403)

    user_email: str = _sanitize_header(row["user_email"])
    user_groups: str = _sanitize_header(row["user_groups"])
    is_admin = "MCP-Admin" in [g.strip() for g in user_groups.split(",")]

    # --- Build upstream request ---
    # Route /mcp paths to FastMCP port (8001), everything else to REST API (8000)
    base_url = MCP_PROXY_MCP_URL if path.startswith("mcp") else MCP_PROXY_URL
    upstream_url = f"{base_url}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Forward headers, replacing auth with identity headers
    forward_headers = dict(request.headers)
    # Remove hop-by-hop / auth headers
    for h in ("host", "authorization", "content-length", "transfer-encoding"):
        forward_headers.pop(h, None)

    forward_headers["X-User-Email"] = user_email
    forward_headers["X-User-Groups"] = user_groups
    forward_headers["X-User-Admin"] = str(is_admin).lower()
    # mcp-proxy (FastMCP) expects this header name
    forward_headers["X-OpenWebUI-User-Email"] = user_email
    forward_headers["X-OpenWebUI-User-Groups"] = user_groups

    body = await request.body()

    # --- Proxy to MCP ---
    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
        upstream_request = client.build_request(
            method=request.method,
            url=upstream_url,
            headers=forward_headers,
            content=body if body else None,
        )
        upstream_response = await client.send(upstream_request, stream=True)

        content_type = upstream_response.headers.get("content-type", "")

        def _filter_headers(resp):
            skip = {"transfer-encoding", "content-length", "content-encoding"}
            return {k: v for k, v in resp.headers.items() if k.lower() not in skip}

        # SSE / streaming responses
        if "text/event-stream" in content_type:
            async def stream_generator():
                try:
                    async for chunk in upstream_response.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_response.aclose()
                    await client.aclose()

            return StreamingResponse(
                stream_generator(),
                status_code=upstream_response.status_code,
                headers=_filter_headers(upstream_response),
                media_type=content_type,
            )

        # Regular responses — read fully then close
        try:
            resp_body = await upstream_response.aread()
        finally:
            await upstream_response.aclose()
            await client.aclose()

        return StreamingResponse(
            iter([resp_body]),
            status_code=upstream_response.status_code,
            headers=_filter_headers(upstream_response),
            media_type=content_type or "application/json",
        )

    except httpx.ConnectError:
        logger.error("Cannot reach MCP proxy at %s", MCP_PROXY_URL)
        return JSONResponse({"error": "MCP proxy unavailable"}, status_code=502)
    except Exception:
        logger.exception("Proxy error")
        return JSONResponse({"error": "Internal proxy error"}, status_code=502)
