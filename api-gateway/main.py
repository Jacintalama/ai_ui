# api-gateway/main.py
"""
API Gateway - Centralized Authentication & Rate Limiting

This gateway sits between Caddy and backend services to provide:
1. JWT validation (validates Open WebUI session tokens)
2. User info extraction + group lookup from PostgreSQL
3. Rate limiting (per user + per IP)
4. Header injection for downstream services
5. API analytics logging
"""

import os
import time
import asyncio
import logging
from typing import Optional, Dict, List
from collections import defaultdict
from contextlib import asynccontextmanager

import jwt
import asyncpg
from fastapi import FastAPI, Request, HTTPException, Response, APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
import httpx

# =============================================================================
# Configuration
# =============================================================================

WEBUI_SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
RATE_LIMIT_PER_IP = int(os.getenv("RATE_LIMIT_PER_IP", "1000"))
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
ENABLE_API_ANALYTICS = os.getenv("ENABLE_API_ANALYTICS", "true").lower() == "true"

MCP_PROXY_URL = os.getenv("MCP_PROXY_URL", "http://mcp-proxy:8000")
ADMIN_PORTAL_URL = os.getenv("ADMIN_PORTAL_URL", "http://admin-portal:8080")
OPEN_WEBUI_URL = os.getenv("OPEN_WEBUI_URL", "http://open-webui:8080")

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Database Connection
# =============================================================================

db_pool: Optional[asyncpg.Pool] = None


async def init_db_pool():
    global db_pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set - group lookup disabled")
        return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10, command_timeout=30)
        logger.info("Database pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")


async def close_db_pool():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        async with self.lock:
            now = time.time()
            window_start = now - window_seconds
            self.requests[key] = [t for t in self.requests[key] if t > window_start]
            current_count = len(self.requests[key])
            if current_count >= limit:
                return False, 0
            self.requests[key].append(now)
            return True, limit - current_count - 1

    async def cleanup(self):
        async with self.lock:
            now = time.time()
            stale_keys = [k for k, times in self.requests.items() if not times or max(times) < now - 120]
            for key in stale_keys:
                del self.requests[key]


rate_limiter = RateLimiter()


# =============================================================================
# JWT & User Lookup
# =============================================================================

def validate_jwt(token: str) -> Optional[dict]:
    if not WEBUI_SECRET_KEY:
        return None
    try:
        return jwt.decode(token, WEBUI_SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def lookup_user_email(user_id: str) -> Optional[str]:
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow('SELECT email FROM "user" WHERE id = $1', user_id)
            return row["email"] if row else None
    except Exception as e:
        logger.error(f"Email lookup error: {e}")
        return None


async def get_user_groups(email: str) -> List[str]:
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT group_name FROM mcp_proxy.user_group_membership WHERE user_email = $1",
                email.lower()
            )
            return [row["group_name"] for row in rows]
    except Exception as e:
        logger.error(f"Group lookup error: {e}")
        return []


async def is_user_admin(email: str) -> bool:
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow('SELECT role FROM "user" WHERE email = $1', email.lower())
            return row and row["role"] == "admin"
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return False


# =============================================================================
# Analytics
# =============================================================================

async def log_request(user_email, method, path, status_code, response_time_ms, user_agent, client_ip):
    if not ENABLE_API_ANALYTICS or not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_proxy.api_analytics
                   (user_email, method, endpoint, status_code, response_time_ms, user_agent, client_ip)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                user_email, method, path, status_code, response_time_ms, user_agent, client_ip
            )
    except Exception as e:
        logger.debug(f"Analytics logging error: {e}")


# =============================================================================
# FastAPI App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()

    async def cleanup_task():
        while True:
            await asyncio.sleep(60)
            await rate_limiter.cleanup()

    cleanup = asyncio.create_task(cleanup_task())
    yield
    cleanup.cancel()
    await close_db_pool()


app = FastAPI(
    title="API Gateway",
    description="Centralized authentication, rate limiting, and routing",
    version="1.0.0",
    lifespan=lifespan
)


# =============================================================================
# Gateway-specific routes (MUST be defined BEFORE catch-all)
# =============================================================================

@app.get("/gateway/health")
async def gateway_health():
    """Gateway health check - returns JSON directly, not proxied."""
    return JSONResponse(content={
        "status": "healthy",
        "service": "api-gateway",
        "database": "connected" if db_pool else "disconnected",
        "rate_limiting": RATE_LIMIT_ENABLED,
        "analytics": ENABLE_API_ANALYTICS
    })


@app.get("/gateway/stats")
async def gateway_stats():
    """Gateway statistics."""
    return JSONResponse(content={
        "rate_limiter_keys": len(rate_limiter.requests),
        "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE,
        "rate_limit_per_ip": RATE_LIMIT_PER_IP
    })


@app.get("/health")
async def health():
    """Simple health check."""
    return JSONResponse(content={"status": "ok"})


# =============================================================================
# Proxy Helper
# =============================================================================

async def forward_request(request: Request, backend_url: str, backend_path: str, extra_headers: dict) -> Response:
    """Forward request to backend service."""
    url = f"{backend_url}{backend_path}"
    if request.query_params:
        url = f"{url}?{request.query_params}"

    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in ["host", "connection", "keep-alive", "transfer-encoding"]:
            headers[key] = value
    headers.update(extra_headers)

    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        body = await request.body()

    logger.debug(f"Forwarding {request.method} -> {url}")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body
        )

        # Build response headers, properly handling multiple Set-Cookie headers
        # httpx.Headers is a multi-dict, but FastAPI Response needs special handling
        response_headers = {}
        for key, value in response.headers.items():
            # Skip hop-by-hop headers that shouldn't be forwarded
            if key.lower() in ["transfer-encoding", "connection", "keep-alive"]:
                continue
            response_headers[key] = value

        # Create the response
        fastapi_response = Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type")
        )

        # Copy headers, handling Set-Cookie specially (can have multiple values)
        for key, value in response.headers.multi_items():
            if key.lower() in ["transfer-encoding", "connection", "keep-alive"]:
                continue
            if key.lower() == "set-cookie":
                # Append each Set-Cookie header individually
                fastapi_response.headers.append(key, value)
            elif key.lower() not in [h.lower() for h in fastapi_response.headers.keys()]:
                fastapi_response.headers[key] = value

        return fastapi_response


# =============================================================================
# Main Proxy Handler (catch-all - MUST be last)
# =============================================================================

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_handler(path: str, request: Request):
    """Main proxy handler - validates auth and forwards to backend."""
    start_time = time.time()
    full_path = f"/{path}"
    method = request.method
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    # Extract JWT from Authorization header OR session cookie
    # API requests: Authorization: Bearer <token>
    # Browser requests: Cookie: token=<token>
    auth_header = request.headers.get("authorization", "")
    user_email = None
    user_groups = []
    is_admin = False
    token = None

    # Debug: Log path and available cookies for /mcp-admin
    if full_path.startswith("/mcp-admin"):
        cookie_names = list(request.cookies.keys())
        logger.info(f"[DEBUG /mcp-admin] Path={full_path}, Cookies={cookie_names}, Auth header present={bool(auth_header)}")

    # Try Authorization header first (API requests)
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        logger.debug("Found JWT in Authorization header")
    else:
        # Try session cookie (browser requests)
        # Open WebUI stores JWT in 'token' cookie
        token = request.cookies.get("token")
        if token:
            logger.debug(f"Found JWT in session cookie (length={len(token)})")

    if token:
        claims = validate_jwt(token)
        if claims:
            user_email = claims.get("email") or claims.get("preferred_username")
            if not user_email and claims.get("id"):
                user_email = await lookup_user_email(claims["id"])
            if user_email:
                user_groups = await get_user_groups(user_email)
                is_admin = await is_user_admin(user_email)
                logger.info(f"Auth OK: {user_email} -> groups={user_groups}, admin={is_admin}")

    # Skip rate limiting for static assets (defense-in-depth, Caddy also bypasses)
    is_static_asset = (
        full_path.startswith("/_app/")
        or full_path.startswith("/static/")
        or full_path.startswith("/favicon")
        or full_path == "/manifest.json"
    )

    # Rate limiting
    if RATE_LIMIT_ENABLED and not is_static_asset:
        rate_key = f"user:{user_email}" if user_email else f"ip:{client_ip}"
        limit = RATE_LIMIT_PER_MINUTE if user_email else RATE_LIMIT_PER_IP
        allowed, remaining = await rate_limiter.is_allowed(rate_key, limit)
        if not allowed:
            response_time = int((time.time() - start_time) * 1000)
            await log_request(user_email, method, full_path, 429, response_time, user_agent, client_ip)
            raise HTTPException(status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"})

    # Build gateway headers
    gateway_headers = {
        "X-User-Email": user_email or "",
        "X-User-Groups": ",".join(user_groups) if user_groups else "",
        "X-User-Admin": "true" if is_admin else "false",
        "X-User-Name": user_email.split("@")[0] if user_email else "",
        "X-Gateway-Validated": "true",
    }

    # Determine backend and path
    # /mcp-admin → MCP Proxy's fancy portal UI
    if full_path == "/mcp-admin" or full_path == "/mcp-admin/":
        backend_url = MCP_PROXY_URL
        backend_path = "/portal"
    # /mcp-admin/* → MCP Proxy (portal assets and API)
    elif full_path.startswith("/mcp-admin/"):
        backend_url = MCP_PROXY_URL
        # Map /mcp-admin/api/* to /admin/* for MCP Proxy
        if full_path.startswith("/mcp-admin/api/"):
            backend_path = "/admin" + full_path[14:]  # /mcp-admin/api/x -> /admin/x
        else:
            backend_path = "/portal" + full_path[10:]  # /mcp-admin/x -> /portal/x
    # MCP Admin API routes → MCP Proxy (NOT Open WebUI)
    # These are used by the /mcp-admin portal for user/group/server management
    elif full_path in ["/admin/users", "/admin/groups", "/admin/servers",
                       "/admin/endpoints", "/admin/tenant-keys", "/admin/analytics"]:
        backend_url = MCP_PROXY_URL
        backend_path = full_path
    elif full_path.startswith("/admin/users/") and not full_path.startswith("/admin/users/overview"):
        # /admin/users/{id} → MCP Proxy (but /admin/users/overview → Open WebUI)
        backend_url = MCP_PROXY_URL
        backend_path = full_path
    elif full_path.startswith("/admin/groups/"):
        backend_url = MCP_PROXY_URL
        backend_path = full_path
    # /mcp/meeting-kb/api/* → Meeting KB upload API (bypass MCP Proxy)
    elif full_path.startswith("/mcp/meeting-kb/api"):
        backend_url = os.getenv("MEETING_KB_URL", "http://meeting-kb:8200")
        backend_path = full_path[16:]  # strip "/mcp/meeting-kb" → "/api/..."
    # /mcp/* → MCP Proxy (tool endpoints)
    elif full_path.startswith("/mcp"):
        backend_url = MCP_PROXY_URL
        backend_path = full_path[4:] if len(full_path) > 4 else "/"
    # /portal → Redirect to /mcp-admin (no redundancy)
    elif full_path.startswith("/portal"):
        return RedirectResponse(url="/mcp-admin", status_code=301)
    elif full_path.startswith("/servers") or full_path.startswith("/meta") or full_path.startswith("/openapi"):
        backend_url = MCP_PROXY_URL
        backend_path = full_path
    else:
        # Everything else goes to Open WebUI (including /admin/* for WebUI admin panel)
        backend_url = OPEN_WEBUI_URL
        backend_path = full_path

    try:
        response = await forward_request(request, backend_url, backend_path, gateway_headers)
        response_time = int((time.time() - start_time) * 1000)
        await log_request(user_email, method, full_path, response.status_code, response_time, user_agent, client_ip)
        return response
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        response_time = int((time.time() - start_time) * 1000)
        await log_request(user_email, method, full_path, 502, response_time, user_agent, client_ip)
        raise HTTPException(status_code=502, detail=f"Backend error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
