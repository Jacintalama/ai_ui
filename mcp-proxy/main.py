# mcp-proxy/main.py
"""
MCP Proxy Gateway - Unified Multi-Tenant Router

Provides unified URL routing for all MCP servers:
  - /{server}/{tool} - Hierarchical routing (Lukas's requirement)
  - /{tenant}_{tool} - Legacy flat routing (backward compatible)

Deployment: Kubernetes localhost:8080

URL Examples:
  GET  /                           - List all available servers
  GET  /github                     - List GitHub tools
  POST /github/search_repositories - Execute GitHub tool
  POST /github_search_repositories - Legacy format (still works)
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import httpx
import asyncio
import os
from contextlib import asynccontextmanager

from auth import extract_user_from_headers, extract_user_from_headers_optional
from tenants import (
    get_tenant, TENANTS,
    get_server, get_all_servers, ALL_SERVERS, ServerTier,
    MCPServerConfig,
    user_has_tenant_access_async, get_user_tenants_async,
    user_has_server_access_async, get_user_tenants_configs_async
)


# Global cache for tools
TOOLS_CACHE: Dict[str, Dict[str, Any]] = {}
OPENAPI_SCHEMAS_CACHE: Dict[str, Any] = {}


class ToolExecuteRequest(BaseModel):
    """Request body for tool execution."""
    arguments: Dict[str, Any] = {}


async def fetch_openapi_from_tenant(tenant_id: str, endpoint: str, api_key: str) -> Optional[Dict]:
    """Fetch OpenAPI spec from a tenant's MCP server."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{endpoint}/openapi.json",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Error fetching OpenAPI from {tenant_id}: {e}")
    return None


async def refresh_tools_cache():
    """Fetch and cache tools from all configured servers."""
    global TOOLS_CACHE, OPENAPI_SCHEMAS_CACHE

    print("Refreshing tools cache from all servers...")

    # Iterate over ALL_SERVERS (11 servers) instead of just TENANTS (3)
    for server_id, server in ALL_SERVERS.items():
        api_key = os.getenv(server.api_key_env, "test-key") if server.api_key_env else "test-key"

        openapi = await fetch_openapi_from_tenant(
            server_id,
            server.endpoint_url,
            api_key
        )

        if not openapi:
            print(f"  {server_id}: No OpenAPI available (may be offline or external)")
            continue

        OPENAPI_SCHEMAS_CACHE[server_id] = openapi

        # Extract tools from OpenAPI paths
        tools_count = 0
        for path, methods in openapi.get("paths", {}).items():
            if path in ["/health", "/docs", "/openapi.json", "/redoc", "/"]:
                continue

            for method, spec in methods.items():
                if method.lower() == "post":
                    original_name = path.strip("/").replace("/", "_")
                    tool_name = f"{server_id}_{original_name}"

                    TOOLS_CACHE[tool_name] = {
                        "name": tool_name,
                        "original_name": original_name,
                        "original_path": path,
                        "tenant_id": server_id,
                        "tenant_name": server.display_name,
                        "description": spec.get("summary", spec.get("description", f"{server.display_name}: {original_name}")),
                        "request_body": spec.get("requestBody", {}),
                        "responses": spec.get("responses", {}),
                        "parameters": spec.get("parameters", [])
                    }
                    tools_count += 1

        if tools_count > 0:
            print(f"  {server_id}: Cached {tools_count} tools")

    print(f"Cached {len(TOOLS_CACHE)} tools from {len(ALL_SERVERS)} servers")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup: refresh tools cache with retry logic
    # MCP servers may not be ready immediately on Kubernetes startup
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(1, max_retries + 1):
        print(f"Refreshing tools cache (attempt {attempt}/{max_retries})...")
        await refresh_tools_cache()

        if TOOLS_CACHE:
            print(f"Tools cache loaded successfully: {len(TOOLS_CACHE)} tools")
            break
        else:
            if attempt < max_retries:
                print(f"No tools cached yet, waiting {retry_delay}s before retry...")
                await asyncio.sleep(retry_delay)
            else:
                print("Warning: Could not load tools after all retries. Use POST /refresh to reload.")

    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="MCP Proxy Gateway - Unified",
    description="""
Multi-tenant MCP proxy with unified URL routing.

## URL Structure (Lukas's Requirement)
- `/{server}/{tool}` - Hierarchical routing
- `/{server}` - List tools for a server
- `/` - List all available servers

## Servers Available
- `/github/*` - GitHub (26 tools)
- `/filesystem/*` - File access (14 tools)
- `/linear/*` - Linear issues
- `/notion/*` - Notion pages
- `/atlassian/*` - Jira/Confluence (via mcpo)
- `/asana/*` - Asana tasks (via mcpo)

## Deployment
Kubernetes cluster on localhost:8080
""",
    version="0.3.0",
    lifespan=lifespan,
    openapi_url=None  # Disable auto-generated OpenAPI, we provide our own
)


async def generate_dynamic_openapi() -> Dict[str, Any]:
    """Generate OpenAPI spec with all cached tools as endpoints (no filtering)."""
    return await generate_dynamic_openapi_filtered(None, None)


async def generate_dynamic_openapi_filtered(user_email: Optional[str], entra_groups: Optional[List[str]]) -> Dict[str, Any]:
    """Generate OpenAPI spec with tools filtered by user access (ASYNC - uses database)."""

    paths = {
        "/health": {
            "get": {
                "summary": "Health Check",
                "operationId": "health_check",
                "responses": {"200": {"description": "Healthy"}}
            }
        },
        "/servers": {
            "get": {
                "summary": "List All Servers",
                "description": "List all available MCP servers organized by tier",
                "operationId": "list_servers",
                "responses": {"200": {"description": "List of servers"}}
            }
        },
        "/refresh": {
            "post": {
                "summary": "Refresh Tools Cache",
                "operationId": "refresh_cache",
                "responses": {"200": {"description": "Cache refreshed"}}
            }
        }
    }

    # Add hierarchical endpoints for each server (filtered by user access)
    for server_id, config in ALL_SERVERS.items():
        # Filter by user access if user is identified
        if user_email:
            if not await user_has_tenant_access_async(user_email, server_id, entra_groups):
                continue  # Skip servers user doesn't have access to

        # GET /{server_id} - List tools for this server
        paths[f"/{server_id}"] = {
            "get": {
                "summary": f"List {config.display_name} Tools",
                "description": f"Get available tools for {config.display_name} ({config.tier.value})",
                "operationId": f"list_{server_id}_tools",
                "responses": {
                    "200": {"description": f"List of {config.display_name} tools"},
                    "403": {"description": "Access Denied"},
                    "404": {"description": "Server not found"}
                }
            }
        }

    # Add hierarchical tool endpoints for cached tools (filtered by user access)
    for tool_name, tool_info in TOOLS_CACHE.items():
        server_id = tool_info["tenant_id"]
        original_name = tool_info["original_name"]

        # Filter by user access if user is identified
        if user_email:
            if not await user_has_tenant_access_async(user_email, server_id, entra_groups):
                continue  # Skip tools from servers user doesn't have access to

        # POST /{server_id}/{tool_name} - Hierarchical format (preferred)
        # Use original request_body schema if available (so AI knows what params to send)
        request_body = tool_info.get("request_body", {})
        if not request_body:
            request_body = {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": True
                        }
                    }
                }
            }

        paths[f"/{server_id}/{original_name}"] = {
            "post": {
                "summary": tool_info["description"],
                "description": f"Server: {tool_info['tenant_name']} | Tool: {original_name}",
                "operationId": f"{server_id}_{original_name}",
                "requestBody": request_body,
                "responses": {
                    "200": {"description": "Successful Response"},
                    "403": {"description": "Access Denied"},
                    "404": {"description": "Tool not found"},
                    "500": {"description": "Execution failed"}
                }
            }
        }

        # POST /{tenant}_{tool} - Legacy format (backward compatibility)
        paths[f"/{tool_name}"] = {
            "post": {
                "summary": f"[Legacy] {tool_info['description']}",
                "description": f"LEGACY FORMAT. Prefer: POST /{server_id}/{original_name}",
                "operationId": f"legacy_{tool_name}",
                "deprecated": True,
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": True
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Successful Response"},
                    "403": {"description": "Access Denied"},
                    "404": {"description": "Tool not found"},
                    "500": {"description": "Execution failed"}
                }
            }
        }

    # Merge component schemas from all cached OpenAPI specs
    components = {"schemas": {}}
    for server_id, openapi_spec in OPENAPI_SCHEMAS_CACHE.items():
        if "components" in openapi_spec and "schemas" in openapi_spec["components"]:
            components["schemas"].update(openapi_spec["components"]["schemas"])

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "MCP Proxy Gateway - Unified",
            "description": """
Unified MCP Proxy for Kubernetes (localhost:8080)

## URL Structure (Lukas's Requirement)
- `GET /servers` - List all available servers
- `GET /{server}` - List tools for a server
- `POST /{server}/{tool}` - Execute a tool (preferred)
- `POST /{server}_{tool}` - Legacy format (deprecated)

## Examples
- `GET /github` - List GitHub tools
- `POST /github/search_repositories` - Search repos
- `POST /filesystem/read_file` - Read a file
""",
            "version": "0.3.0"
        },
        "paths": paths,
        "components": components
    }


@app.get("/openapi.json", include_in_schema=False)
async def custom_openapi(request: Request):
    """Return dynamically generated OpenAPI spec with tools filtered by user access."""
    # Extract user info for filtering
    user = extract_user_from_headers_optional(request)
    user_email = user.email if user else None
    entra_groups = user.entra_groups if user else None

    print(f"=== /openapi.json request ===")
    print(f"  User email: {user_email}")

    # Generate filtered OpenAPI spec (async for database lookups)
    openapi_spec = await generate_dynamic_openapi_filtered(user_email, entra_groups)
    return JSONResponse(content=openapi_spec)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "mcp-proxy",
        "tools_cached": len(TOOLS_CACHE),
        "tenants": len(TENANTS)
    }


@app.post("/refresh")
async def refresh_cache(request: Request):
    """Manually refresh the tools cache."""
    await refresh_tools_cache()
    return {
        "status": "refreshed",
        "tools_count": len(TOOLS_CACHE),
        "tools": list(TOOLS_CACHE.keys())
    }


@app.get("/debug/user")
async def debug_user(request: Request):
    """Debug endpoint to test header extraction."""
    try:
        user = extract_user_from_headers(request)
        return {
            "email": user.email,
            "user_id": user.user_id,
            "name": user.name,
            "role": user.role,
            "chat_id": user.chat_id
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/headers")
async def debug_headers(request: Request):
    """Show all incoming headers for debugging."""
    return dict(request.headers)


@app.get("/debug/tools")
async def debug_tools():
    """List all cached tools."""
    return {
        "tool_count": len(TOOLS_CACHE),
        "tools": list(TOOLS_CACHE.keys())
    }


@app.get("/tenants")
async def list_tenants(request: Request):
    """List tenants the current user has access to."""
    user = extract_user_from_headers(request)
    tenants = await get_user_tenants_configs_async(user.email, user.entra_groups if user else None)
    return {
        "user": user.email,
        "tenants": [
            {
                "tenant_id": t.tenant_id,
                "display_name": t.display_name,
                "enabled": t.enabled
            }
            for t in tenants
        ]
    }


@app.get("/tools")
async def list_tools(request: Request):
    """List tools available to the current user based on tenant access."""
    user = extract_user_from_headers(request)

    # Use async database lookup for tenant access
    tenant_ids = await get_user_tenants_async(user.email, user.entra_groups if user else None)

    if not tenant_ids:
        return {
            "user": user.email,
            "tools": [],
            "message": "No tenant access configured for this user"
        }

    user_tools = [
        tool for tool_name, tool in TOOLS_CACHE.items()
        if tool["tenant_id"] in tenant_ids
    ]

    return {
        "user": user.email,
        "tenant_count": len(tenant_ids),
        "tool_count": len(user_tools),
        "tools": user_tools
    }


# =============================================================================
# UNIFIED HIERARCHICAL ROUTING (Lukas's Requirement)
# =============================================================================
# URL Structure: /{server}/{tool}
# Example: /github/search_repositories, /linear/list_issues
# =============================================================================

# Environment variable to control anonymous access to server listing
REQUIRE_AUTH_FOR_LISTING = os.getenv("REQUIRE_AUTH_FOR_LISTING", "true").lower() == "true"


@app.get("/servers")
async def list_all_servers(request: Request):
    """
    List all available MCP servers (filtered by user access).

    Returns servers organized by tier:
    - Tier 1 (HTTP): Direct connection
    - Tier 2 (SSE): Via mcpo-sse proxy
    - Tier 3 (stdio): Via mcpo-stdio proxy
    - Local: In-cluster containers

    Multi-tenant filtering:
    - Extracts user from X-OpenWebUI-User-Email header
    - Returns only servers the user has access to
    - If user cannot be identified and REQUIRE_AUTH_FOR_LISTING=true, returns empty list
    """
    # Extract user info
    user = extract_user_from_headers_optional(request)
    user_email = user.email if user else None
    entra_groups = user.entra_groups if user else None

    # Debug: Log what we received
    print(f"=== /servers request ===")
    print(f"  User email: {user_email}")
    print(f"  Entra groups: {entra_groups}")
    print(f"  Group count: {len(entra_groups) if entra_groups else 0}")
    print(f"  Headers:")
    print(f"    X-OpenWebUI-User-Email = {request.headers.get('X-OpenWebUI-User-Email', 'NOT SET')}")
    print(f"    X-OpenWebUI-User-Groups = {request.headers.get('X-OpenWebUI-User-Groups', 'NOT SET')}")
    print(f"    X-User-Groups = {request.headers.get('X-User-Groups', 'NOT SET')}")

    # If no user identified and auth is required, return empty list
    if not user_email and REQUIRE_AUTH_FOR_LISTING:
        print(f"  WARN: No user identified, returning empty server list")
        return {
            "total_servers": 0,
            "servers": [],
            "by_tier": {},
            "message": "User not identified. Ensure ENABLE_FORWARD_USER_INFO_HEADERS=true in Open WebUI.",
            "usage": {
                "list_tools": "GET /{server_id}",
                "execute_tool": "POST /{server_id}/{tool_name}",
                "example": "POST /github/search_repositories"
            }
        }

    servers = []
    for server_id, config in ALL_SERVERS.items():
        # Filter by user access if user is identified
        if user_email:
            # Use async database lookup for production
            has_access = await user_has_tenant_access_async(user_email, server_id, entra_groups)
            print(f"  Checking {user_email} access to {server_id}: {has_access}")
            if not has_access:
                continue  # Skip servers user doesn't have access to

        servers.append({
            "id": server_id,
            "name": config.display_name,
            "tier": config.tier.value,
            "description": config.description,
            "enabled": config.enabled,
            "endpoint": f"/{server_id}/",
            "tools_endpoint": f"/{server_id}",
        })

    print(f"  Returning {len(servers)} servers for user {user_email}")

    # Group by tier for easier reading
    by_tier = {}
    for s in servers:
        tier = s["tier"]
        if tier not in by_tier:
            by_tier[tier] = []
        by_tier[tier].append(s)

    return {
        "total_servers": len(servers),
        "servers": servers,
        "by_tier": by_tier,
        "usage": {
            "list_tools": "GET /{server_id}",
            "execute_tool": "POST /{server_id}/{tool_name}",
            "example": "POST /github/search_repositories"
        }
    }


async def fetch_server_tools(server: MCPServerConfig) -> List[Dict]:
    """Fetch available tools from a server."""
    # For local servers, use cached tools
    if server.tier == ServerTier.LOCAL:
        return [
            {
                "name": tool["original_name"],
                "description": tool["description"],
                "endpoint": f"/{server.server_id}/{tool['original_name']}"
            }
            for tool_name, tool in TOOLS_CACHE.items()
            if tool["tenant_id"] == server.server_id
        ]

    # For remote servers, try to fetch OpenAPI
    try:
        api_key = os.getenv(server.api_key_env, "") if server.api_key_env else ""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{server.endpoint_url}/openapi.json",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if response.status_code == 200:
                openapi = response.json()
                tools = []
                for path, methods in openapi.get("paths", {}).items():
                    if path in ["/health", "/docs", "/openapi.json", "/redoc", "/"]:
                        continue
                    for method, spec in methods.items():
                        if method.lower() == "post":
                            tool_name = path.strip("/").replace("/", "_")
                            tools.append({
                                "name": tool_name,
                                "description": spec.get("summary", tool_name),
                                "endpoint": f"/{server.server_id}/{tool_name}"
                            })
                return tools
    except Exception as e:
        print(f"Error fetching tools from {server.server_id}: {e}")

    return [{"error": f"Could not fetch tools from {server.server_id}"}]


async def execute_on_server(server: MCPServerConfig, tool_path: str, body: dict) -> Any:
    """Execute a tool on any server based on its tier."""
    api_key = os.getenv(server.api_key_env, "test-key") if server.api_key_env else "test-key"

    # Build the full URL
    # For local servers, tool_path might already have leading slash
    clean_path = tool_path.strip("/")
    url = f"{server.endpoint_url}/{clean_path}"

    print(f"=== Executing on {server.server_id} ===")
    print(f"  Tier: {server.tier.value}")
    print(f"  URL: {url}")
    print(f"  Body: {body}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            print(f"  Response: {response.status_code}")

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Server {server.server_id} returned: {response.text}"
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error calling {server.server_id}: {str(e)}"
        )


async def execute_tool_on_tenant(tenant_id: str, original_path: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool on the tenant's MCP server."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return {"success": False, "error": f"Tenant {tenant_id} not found"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {tenant.mcp_api_key}",
                "Content-Type": "application/json"
            }

            # Inject tenant-specific credentials
            for key, value in tenant.credentials.items():
                headers[f"X-Tenant-{key}"] = value

            response = await client.post(
                f"{tenant.mcp_endpoint}{original_path}",
                json=arguments,
                headers=headers
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# HIERARCHICAL ENDPOINTS: /{server_id} and /{server_id}/{tool_path}
# =============================================================================

# List of known server IDs to distinguish from legacy tool names
KNOWN_SERVER_IDS = set(ALL_SERVERS.keys())


@app.get("/{server_id}")
async def get_server_tools(server_id: str, request: Request):
    """
    Get information and available tools for a specific server.

    Example: GET /github -> Returns list of GitHub tools
    """
    # Check if this is a known server
    server = get_server(server_id)
    if not server:
        # Not a server, might be a debug endpoint or invalid
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_id}' not found. Use GET /servers for available servers."
        )

    # Check user access
    user = extract_user_from_headers_optional(request)
    if user:
        has_access = await user_has_tenant_access_async(user.email, server_id, user.entra_groups if user else None)
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail=f"User {user.email} does not have access to server '{server_id}'"
            )

    # Fetch tools for this server
    tools = await fetch_server_tools(server)

    # Get example tool name safely (tools might be error objects or empty)
    example_tool = "tool_name"
    if tools and isinstance(tools[0], dict) and "name" in tools[0]:
        example_tool = tools[0]["name"]

    return {
        "server": server_id,
        "name": server.display_name,
        "tier": server.tier.value,
        "description": server.description,
        "enabled": server.enabled,
        "tool_count": len([t for t in tools if "name" in t]),  # Only count valid tools
        "tools": tools,
        "usage": {
            "execute": f"POST /{server_id}/{{tool_name}}",
            "example": f"POST /{server_id}/{example_tool}"
        }
    }


@app.post("/{server_id}/{tool_path:path}")
async def execute_server_tool(server_id: str, tool_path: str, request: Request):
    """
    Execute a tool on a specific server using hierarchical URL.

    Examples:
        POST /github/search_repositories {"query": "mcp"}
        POST /linear/list_issues {"project": "ABC"}
        POST /filesystem/read_file {"path": "/data/file.txt"}
    """
    # Check if this is a known server
    server = get_server(server_id)
    if not server:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_id}' not found. Use GET /servers for available servers."
        )

    if not server.enabled:
        raise HTTPException(
            status_code=503,
            detail=f"Server '{server_id}' is currently disabled"
        )

    # DEBUG: Log ALL headers to see what Open WebUI sends
    print(f"=== Tool Execution: /{server_id}/{tool_path} ===")

    # Try to get user from multiple sources:
    # 1. X-OpenWebUI-User-Email header (preferred)
    # 2. Query parameter ?user_email= (for testing/demo)
    # 3. Default to None
    user = extract_user_from_headers_optional(request)

    # Fallback: check query parameter for demo/testing
    if not user:
        query_email = request.query_params.get("user_email")
        if query_email:
            from auth import UserInfo
            user = UserInfo(
                email=query_email,
                user_id="query_param",
                name=query_email.split("@")[0],
                role="user"
            )
            print(f"  User from query param: {user.email}")

    print(f"  Extracted user: {user.email if user else 'None'}")

    if user:
        # Use async database lookup for production
        has_access = await user_has_tenant_access_async(user.email, server_id, user.entra_groups if user else None)
        if not has_access:
            print(f"  ACCESS DENIED: {user.email} -> {server_id}")
            raise HTTPException(
                status_code=403,
                detail=f"User {user.email} does not have access to server '{server_id}'"
            )
        print(f"  ACCESS GRANTED: {user.email} -> {server_id}")
    else:
        print(f"  WARNING: No user identified, allowing anonymous access")

    # Parse request body
    try:
        body = await request.json()
    except:
        body = {}

    print(f"=== Hierarchical Route: /{server_id}/{tool_path} ===")
    print(f"  Raw body received: {body}")

    # Handle Open WebUI format: might send {"arguments": {...}} instead of direct params
    if "arguments" in body and isinstance(body["arguments"], dict):
        print(f"  Unwrapping 'arguments' key")
        body = body["arguments"]
        print(f"  Unwrapped body: {body}")

    # Execute based on server tier
    return await execute_on_server(server, tool_path, body)


# =============================================================================
# LEGACY ENDPOINT (Backward Compatibility)
# =============================================================================
# Format: /{tenant}_{tool_name} (e.g., /github_search_repositories)
# Kept for backward compatibility with existing integrations
# =============================================================================

@app.post("/{tool_name}")
async def execute_tool_endpoint_legacy(tool_name: str, request: Request):
    """
    LEGACY: Execute a tool using flat URL format.

    Format: /{tenant}_{tool_name}
    Example: /github_search_repositories

    NOTE: Prefer using hierarchical format: /{server}/{tool}
          Example: /github/search_repositories
    """
    # DEBUG: Log all incoming headers
    print(f"=== Legacy Tool Call: {tool_name} ===")
    print("Headers received:")
    for key, value in request.headers.items():
        # Mask sensitive values but show they exist
        if key.lower() in ['authorization', 'cookie']:
            print(f"  {key}: {value[:50]}..." if len(value) > 50 else f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")

    # Get tool info from cache
    tool_info = TOOLS_CACHE.get(tool_name)
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    tenant_id = tool_info["tenant_id"]
    original_path = tool_info["original_path"]

    # Try to extract user for access control
    user = extract_user_from_headers_optional(request)
    print(f"User extracted: {user.email if user else 'None'}")

    if user:
        # Enforce access control if user headers present - use async database lookup
        has_access = await user_has_tenant_access_async(user.email, tenant_id, user.entra_groups if user else None)
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail=f"User {user.email} does not have access to tenant '{tenant_id}'"
            )

    # Parse request body
    try:
        body = await request.json()
    except:
        body = {}

    # Execute the tool
    result = await execute_tool_on_tenant(tenant_id, original_path, body)
    return result
