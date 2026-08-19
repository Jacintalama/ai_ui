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
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import httpx
import asyncio
import os
import re
from contextlib import asynccontextmanager

from auth import extract_user_from_headers, extract_user_from_headers_optional
from tenants import (
    get_tenant, TENANTS,
    get_server, get_all_servers, ALL_SERVERS, ServerTier,
    MCPServerConfig,
    user_has_tenant_access_async, get_user_tenants_async,
    user_has_server_access_async, get_user_tenants_configs_async
)
from db import (
    get_pool,
    get_tenant_api_keys_for_server,
    get_tenant_api_key,
    set_tenant_api_key,
    delete_tenant_api_key,
    get_all_tenant_keys,
    get_tenant_keys_by_tenant,
    get_tenant_endpoint_override,
    # Admin Portal imports
    is_openwebui_admin,
    get_all_users_with_groups,
    add_user_to_group,
    remove_user_from_group,
    get_all_groups_with_servers,
    get_group_users,
    create_group,
    update_group_servers,
    delete_group,
    get_all_tenant_endpoints,
    set_tenant_endpoint_override,
    delete_tenant_endpoint_override,
    get_all_available_servers
)
from tool_embeddings import (
    store_tool_embeddings,
    prune_stale_tools,
    search_tools_by_query,
    get_embeddings_stats
)
from access import (may_use_server, require_identified,
                    servers_for_caller)
from mcp_http_client import get_mcp_client, MCPStreamableClient
from admin_api import admin_router


# Global cache for tools
TOOLS_CACHE: Dict[str, Dict[str, Any]] = {}
OPENAPI_SCHEMAS_CACHE: Dict[str, Any] = {}

# Meta-tools mode: when enabled, OpenAPI spec shows only 3 meta-tools instead of 200+ tools
# This reduces token usage by 96-99% (Speakeasy Dynamic Toolsets pattern)
META_TOOLS_MODE = os.getenv("META_TOOLS_MODE", "false").lower() == "true"


class ToolExecuteRequest(BaseModel):
    """Request body for tool execution."""
    arguments: Dict[str, Any] = {}


class SearchToolsRequest(BaseModel):
    """Request body for search_tools meta-tool."""
    query: str
    limit: int = 10


class DescribeToolsRequest(BaseModel):
    """Request body for describe_tools meta-tool."""
    tool_names: List[str]


class CallToolRequest(BaseModel):
    """Request body for call_tool meta-tool."""
    tool_name: str
    arguments: Dict[str, Any] = {}


async def fetch_openapi_from_tenant(tenant_id: str, endpoint: str, api_key: str) -> Optional[Dict]:
    """Fetch OpenAPI spec from a tenant's MCP server."""
    try:
        print(f"    Fetching OpenAPI from {tenant_id} at {endpoint}...")
        async with httpx.AsyncClient(timeout=3.0) as client:  # Reduced timeout from 10s to 3s
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

    # Iterate over ALL_SERVERS but skip disabled servers to avoid long startup times
    enabled_servers = {k: v for k, v in ALL_SERVERS.items() if v.enabled}
    print(f"  Checking {len(enabled_servers)} enabled servers (skipping {len(ALL_SERVERS) - len(enabled_servers)} disabled)")

    for server_id, server in enabled_servers.items():
        api_key = os.getenv(server.api_key_env, "test-key") if server.api_key_env else "test-key"

        # MCP Streamable HTTP servers use JSON-RPC, not OpenAPI
        if server.tier == ServerTier.MCP_HTTP:
            try:
                client = get_mcp_client(server.endpoint_url, api_key)
                mcp_tools = await client.list_tools()
                tools_count = 0
                for tool in mcp_tools:
                    original_name = tool.get("name", "")
                    tool_name = f"{server_id}_{original_name}"
                    input_schema = tool.get("inputSchema", {})

                    # Convert MCP inputSchema to OpenAPI requestBody format
                    request_body = {}
                    if input_schema:
                        request_body = {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": input_schema
                                }
                            }
                        }

                    TOOLS_CACHE[tool_name] = {
                        "name": tool_name,
                        "original_name": original_name,
                        "original_path": f"/{original_name}",
                        "tenant_id": server_id,
                        "tenant_name": server.display_name,
                        "description": tool.get("description", f"{server.display_name}: {original_name}"),
                        "request_body": request_body,
                        "responses": {"200": {"description": "Successful Response"}},
                        "parameters": [],
                        "_mcp_tool": True,  # Flag for MCP protocol routing
                    }
                    tools_count += 1

                if tools_count > 0:
                    print(f"  {server_id}: Cached {tools_count} MCP tools")
            except Exception as e:
                print(f"  {server_id}: MCP HTTP error: {e}")
            continue

        # Standard OpenAPI servers
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

    # Generate and store embeddings for semantic search (meta-tools)
    if TOOLS_CACHE:
        try:
            pool = await get_pool()
            stored = await store_tool_embeddings(pool, TOOLS_CACHE)
            print(f"Stored {stored} tool embeddings for semantic search")
            # The index upserts and never deletes, so tools from servers that
            # were removed or disabled stayed searchable and then failed at
            # execution. Prune against the enabled registry, not against what
            # answered this boot: a server that is up but momentarily failed to
            # list its tools must keep its rows.
            removed = await prune_stale_tools(pool, set(enabled_servers))
            if removed:
                print(f"Pruned {removed} tools from servers no longer live")
        except Exception as e:
            print(f"Warning: Could not store tool embeddings: {e}")
            print("Meta-tools search will use keyword fallback")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Check if we should skip cache refresh on startup (for faster boot)
    skip_cache = os.getenv("SKIP_CACHE_REFRESH", "false").lower() == "true"

    if skip_cache:
        print("SKIP_CACHE_REFRESH=true - Skipping initial cache refresh")
        print("Use POST /refresh to load tools when MCP servers are ready")
    else:
        # Startup: refresh tools cache with retry logic
        # MCP servers may not be ready immediately on Kubernetes startup
        max_retries = int(os.getenv("CACHE_REFRESH_RETRIES", "3"))
        retry_delay = int(os.getenv("CACHE_REFRESH_DELAY", "5"))

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

# Include admin router FIRST to ensure it has priority over catch-all routes
app.include_router(admin_router)

# Admin Portal UI - serve static HTML
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/portal", response_class=HTMLResponse, include_in_schema=False)
async def admin_portal(request: Request):
    """Serve the Admin Portal UI - ADMIN ONLY.

    Access Control:
    - Not logged in → Redirect to Open WebUI login
    - Logged in but not admin → 403 Forbidden
    - Logged in as admin → Show portal
    """
    # Debug: Log received headers from API Gateway
    x_user_email = request.headers.get("X-User-Email", "")
    x_user_groups = request.headers.get("X-User-Groups", "")
    x_user_admin = request.headers.get("X-User-Admin", "")
    x_gateway = request.headers.get("X-Gateway-Validated", "")
    print(f"[PORTAL] Headers received: X-User-Email={x_user_email}, X-User-Groups={x_user_groups}, X-User-Admin={x_user_admin}, X-Gateway-Validated={x_gateway}")

    # Extract user from headers (set by API Gateway)
    user = await extract_user_from_headers_optional(request)
    print(f"[PORTAL] User extracted: {user}")

    # Not logged in → redirect to login
    if not user or not user.email:
        print(f"[PORTAL] No user found, redirecting to login")
        return RedirectResponse(url="/", status_code=302)

    # Check if user is Open WebUI admin
    is_admin = await is_openwebui_admin(user.email)
    if not is_admin:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Access Denied</title></head>
            <body style="font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e;">
                <div style="text-align: center; color: white;">
                    <h1 style="color: #ff6b6b;">403 - Access Denied</h1>
                    <p>Admin access required to view this page.</p>
                    <p style="color: #888;">You are logged in as: {}</p>
                    <a href="/" style="color: #4ecdc4;">← Back to Open WebUI</a>
                </div>
            </body>
            </html>
            """.format(user.email),
            status_code=403
        )

    # Admin verified → serve portal
    html_path = STATIC_DIR / "admin.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse("<h1>Admin Portal not found</h1><p>static/admin.html is missing</p>", status_code=404)


async def generate_dynamic_openapi() -> Dict[str, Any]:
    """Generate OpenAPI spec with all cached tools as endpoints (no filtering)."""
    return await generate_dynamic_openapi_filtered(None, None)


async def generate_dynamic_openapi_filtered(user_email: Optional[str], entra_groups: Optional[List[str]]) -> Dict[str, Any]:
    """Generate OpenAPI spec with tools filtered by user access (ASYNC - uses database).

    When META_TOOLS_MODE=true, returns only 3 meta-tool endpoints (search, describe, call)
    instead of 200+ individual tool endpoints. This is the Speakeasy Dynamic Toolsets pattern.
    """

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

    # =========================================================================
    # META-TOOLS MODE: Only expose 3 meta-tools instead of 200+ individual tools
    # =========================================================================
    if META_TOOLS_MODE:
        paths["/meta/search_tools"] = {
            "post": {
                "summary": "Search for relevant tools by natural language query",
                "description": (
                    "Find tools that match your intent. For example: "
                    "'create a task in ClickUp', 'read a file', 'search GitHub repos'. "
                    "Returns ranked results with tool names and descriptions. "
                    "Use the returned tool_name values with describe_tools and call_tool."
                ),
                "operationId": "search_tools",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "Natural language description of what you want to do"
                                    },
                                    "limit": {
                                        "type": "integer",
                                        "default": 10,
                                        "description": "Maximum number of results to return"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "List of matching tools with relevance scores"}
                }
            }
        }

        paths["/meta/describe_tools"] = {
            "post": {
                "summary": "Get full parameter schemas for specific tools",
                "description": (
                    "After finding tools with search_tools, use this to get their "
                    "complete parameter schemas before calling them. Pass an array of "
                    "tool_name values from search_tools results."
                ),
                "operationId": "describe_tools",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["tool_names"],
                                "properties": {
                                    "tool_names": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of tool names to describe (from search_tools results)"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Full schemas for requested tools"}
                }
            }
        }

        paths["/meta/call_tool"] = {
            "post": {
                "summary": "Execute any tool by name with provided arguments",
                "description": (
                    "Execute a tool after discovering it with search_tools and "
                    "getting its schema with describe_tools. Provide the full "
                    "tool_name and arguments matching the schema."
                ),
                "operationId": "call_tool",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["tool_name"],
                                "properties": {
                                    "tool_name": {
                                        "type": "string",
                                        "description": "Full tool name (e.g., 'clickup_create_task')"
                                    },
                                    "arguments": {
                                        "type": "object",
                                        "additionalProperties": True,
                                        "description": "Arguments matching the tool's schema from describe_tools"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {"description": "Tool execution result"},
                    "403": {"description": "Access denied"},
                    "404": {"description": "Tool not found"},
                    "500": {"description": "Execution failed"}
                }
            }
        }

        return {
            "openapi": "3.1.0",
            "info": {
                "title": "MCP Proxy Gateway - Meta-Tools",
                "description": f"""
MCP Proxy with Speakeasy Dynamic Toolsets.

Instead of listing {len(TOOLS_CACHE)} individual tools, this proxy exposes 3 meta-tools:

1. **search_tools** - Find relevant tools by natural language query
2. **describe_tools** - Get full parameter schemas for specific tools
3. **call_tool** - Execute any tool by name

## Workflow
1. Call `search_tools` with a description of what you want to do
2. Call `describe_tools` with the tool names from the search results
3. Call `call_tool` with the tool name and arguments

## Example
1. `search_tools({{"query": "create task clickup"}})` → finds `clickup_create_task`
2. `describe_tools({{"tool_names": ["clickup_create_task"]}})` → gets parameter schema
3. `call_tool({{"tool_name": "clickup_create_task", "arguments": {{"name": "My Task"}}}})` → creates the task

This reduces token usage by 96-99% compared to listing all tools.
""",
                "version": "0.4.0"
            },
            "paths": paths,
            "components": {"schemas": {}}
        }

    # =========================================================================
    # STANDARD MODE: Expose all individual tools (original behavior)
    # =========================================================================

    # Add hierarchical endpoints for each server (filtered by user access)
    for server_id, config in ALL_SERVERS.items():
        # An unidentified caller is shown nothing. This read `if user_email:`,
        # so "we do not know who you are" listed every server on the box.
        if not user_email or not await user_has_tenant_access_async(
                user_email, server_id, entra_groups):
            continue

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

        # Same rule for the tools themselves.
        if not user_email or not await user_has_tenant_access_async(
                user_email, server_id, entra_groups):
            continue

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
    user = await extract_user_from_headers_optional(request)
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
        "tenants": len(TENANTS),
        "meta_tools_mode": META_TOOLS_MODE
    }


@app.post("/refresh")
async def refresh_cache(request: Request):
    """Manually refresh the tools cache and regenerate embeddings."""
    await refresh_tools_cache()

    # Get embedding stats
    embedding_info = {}
    try:
        pool = await get_pool()
        embedding_info = await get_embeddings_stats(pool)
    except Exception as e:
        embedding_info = {"error": str(e)}

    return {
        "status": "refreshed",
        "tools_count": len(TOOLS_CACHE),
        "meta_tools_mode": META_TOOLS_MODE,
        "embeddings": embedding_info,
        "tools": list(TOOLS_CACHE.keys())
    }


@app.get("/debug/user")
async def debug_user(request: Request):
    """Debug endpoint to test header extraction."""
    try:
        user = await extract_user_from_headers(request)
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
    """What the proxy sees, for the caller only.

    This returned dict(request.headers) to anyone who asked. The headers are
    the caller's own, so the leak is modest, but it also confirmed to an
    unauthenticated prober exactly which identity headers this service trusts,
    which is the first thing you would want before trying to forge one.
    """
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)
    return {"seen_by_proxy": sorted(request.headers.keys()), "user": user.email}


@app.get("/debug/tools")
async def debug_tools(request: Request):
    """List all cached tools, for an identified caller.

    The full tool inventory of every connected server is a map of what this
    platform is wired into. It had no auth at all.
    """
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)
    return {
        "tool_count": len(TOOLS_CACHE),
        "tools": list(TOOLS_CACHE.keys())
    }


# =============================================================================
# SPEAKEASY META-TOOLS (3 tools replace 200+)
# =============================================================================
# When META_TOOLS_MODE=true, the OpenAPI spec only advertises these 3 endpoints.
# The LLM uses search_tools to find relevant tools, describe_tools to get schemas,
# and call_tool to execute them. This reduces token usage by 96-99%.
# =============================================================================

@app.post("/meta/search_tools")
async def meta_search_tools(body: SearchToolsRequest, request: Request):
    """
    Search for relevant tools using natural language.

    Given a query like "create a task in ClickUp" or "read a file",
    returns the most relevant tools ranked by semantic similarity.

    The LLM should call this first to discover which tools are available
    for a given task, then use describe_tools to get parameter schemas.
    """
    user = await extract_user_from_headers_optional(request)
    user_email = user.email if user else None
    entra_groups = user.entra_groups if user else None

    print(f"=== Meta: search_tools ===")
    print(f"  User: {user_email}")
    print(f"  Query: {body.query}")
    print(f"  Limit: {body.limit}")

    # /meta/* is routed to the public internet, so a caller we cannot identify
    # is refused here rather than filtered later: "unknown" must never widen
    # into "unfiltered".
    require_identified(user_email)
    allowed_servers = servers_for_caller(
        user_email, await get_user_tenants_async(user_email, entra_groups))
    if not allowed_servers:
        return {"query": body.query, "count": 0, "results": [],
                "message": "No server access configured for this user"}

    try:
        pool = await get_pool()
        results = await search_tools_by_query(
            pool, body.query, sorted(allowed_servers), body.limit
        )
        print(f"  Found {len(results)} matching tools")
        return {
            "query": body.query,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        print(f"  Error: {e}")
        # Fallback: search TOOLS_CACHE directly by keyword
        query_lower = body.query.lower()
        matches = []
        for tool_name, tool_info in TOOLS_CACHE.items():
            if not may_use_server(allowed_servers, tool_info["tenant_id"]):
                continue
            name_match = query_lower in tool_name.lower()
            desc_match = query_lower in tool_info.get("description", "").lower()
            if name_match or desc_match:
                matches.append({
                    "tool_name": tool_name,
                    "server_id": tool_info["tenant_id"],
                    "display_name": tool_info.get("original_name", tool_name),
                    "description": tool_info.get("description", ""),
                    "relevance_score": 0.8 if name_match else 0.5
                })
        matches.sort(key=lambda x: x["relevance_score"], reverse=True)
        return {
            "query": body.query,
            "count": len(matches[:body.limit]),
            "results": matches[:body.limit],
            "source": "cache_fallback"
        }


@app.post("/meta/describe_tools")
async def meta_describe_tools(body: DescribeToolsRequest, request: Request):
    """
    Get full parameter schemas for specific tools.

    After using search_tools to find relevant tools, call this with
    the tool names to get their complete request schemas. This enables
    lazy loading - only fetch schemas for tools the LLM actually needs.

    Returns the full requestBody schema, parameters, and server info
    for each requested tool.
    """
    user = await extract_user_from_headers_optional(request)
    user_email = user.email if user else None
    entra_groups = user.entra_groups if user else None

    print(f"=== Meta: describe_tools ===")
    print(f"  User: {user_email}")
    print(f"  Tools: {body.tool_names}")

    require_identified(user_email)
    allowed_servers = servers_for_caller(
        user_email, await get_user_tenants_async(user_email, entra_groups))

    descriptions = []
    for tool_name in body.tool_names:
        tool_info = TOOLS_CACHE.get(tool_name)
        if not tool_info:
            descriptions.append({
                "tool_name": tool_name,
                "error": "Tool not found"
            })
            continue

        # Access control check
        if not may_use_server(allowed_servers, tool_info["tenant_id"]):
            descriptions.append({
                "tool_name": tool_name,
                "error": "Access denied"
            })
            continue

        descriptions.append({
            "tool_name": tool_name,
            "server_id": tool_info["tenant_id"],
            "server_name": tool_info.get("tenant_name", ""),
            "display_name": tool_info.get("original_name", tool_name),
            "description": tool_info.get("description", ""),
            "request_body": tool_info.get("request_body", {}),
            "parameters": tool_info.get("parameters", []),
            "endpoint": f"/{tool_info['tenant_id']}/{tool_info.get('original_name', tool_name)}"
        })

    return {
        "count": len(descriptions),
        "tools": descriptions
    }


@app.post("/meta/call_tool")
async def meta_call_tool(body: CallToolRequest, request: Request):
    """
    Execute any tool by name with provided arguments.

    This is the execution endpoint for the meta-tools pattern.
    After discovering tools with search_tools and getting schemas
    with describe_tools, use this to actually run the tool.

    The tool_name should be the full qualified name (e.g., "clickup_create_task").
    Arguments should match the schema returned by describe_tools.
    """
    user = await extract_user_from_headers_optional(request)
    user_email = user.email if user else None
    entra_groups = user.entra_groups if user else None

    print(f"=== Meta: call_tool ===")
    print(f"  User: {user_email}")
    print(f"  Tool: {body.tool_name}")

    # Refused before the cache is even consulted, so an unidentified caller
    # cannot tell an existing tool from a missing one by the status code.
    require_identified(user_email)

    # Look up tool in cache
    tool_info = TOOLS_CACHE.get(body.tool_name)
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Tool '{body.tool_name}' not found")

    server_id = tool_info["tenant_id"]
    original_path = tool_info["original_path"]

    # Access control check. Unconditional: the caller is known by now, and
    # making this depend on having one is what let anonymous callers execute
    # tools against the platform's own shared credentials.
    has_access = await user_has_tenant_access_async(user_email, server_id, entra_groups)
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail=f"User {user_email} does not have access to server '{server_id}'"
        )

    # Get user's tenant IDs for API key lookup (US-011)
    tenant_ids = await get_user_tenants_async(user_email, entra_groups)

    # Execute via existing infrastructure
    server = get_server(server_id)
    if server and server.enabled:
        return await execute_on_server(server, original_path.strip("/"), body.arguments, tenant_ids, user_email=user_email)

    # Fallback to tenant execution
    return await execute_tool_on_tenant(server_id, original_path, body.arguments, tenant_ids)


@app.get("/meta/stats")
async def meta_stats():
    """Get statistics about tool embeddings."""
    try:
        pool = await get_pool()
        stats = await get_embeddings_stats(pool)
        stats["meta_tools_mode"] = META_TOOLS_MODE
        stats["total_tools_cached"] = len(TOOLS_CACHE)
        return stats
    except Exception as e:
        return {
            "error": str(e),
            "meta_tools_mode": META_TOOLS_MODE,
            "total_tools_cached": len(TOOLS_CACHE)
        }


@app.get("/tenants")
async def list_tenants(request: Request):
    """List tenants the current user has access to."""
    user = await extract_user_from_headers(request)
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
    user = await extract_user_from_headers(request)

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
    user = await extract_user_from_headers_optional(request)
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

    # MCP Streamable HTTP servers: use MCP protocol to list tools
    if server.tier == ServerTier.MCP_HTTP:
        # First check cache
        cached = [
            {
                "name": tool["original_name"],
                "description": tool["description"],
                "endpoint": f"/{server.server_id}/{tool['original_name']}"
            }
            for tool_name, tool in TOOLS_CACHE.items()
            if tool["tenant_id"] == server.server_id
        ]
        if cached:
            return cached

        # Fetch live from MCP server
        try:
            api_key = os.getenv(server.api_key_env, "") if server.api_key_env else ""
            client = get_mcp_client(server.endpoint_url, api_key)
            mcp_tools = await client.list_tools()
            return [
                {
                    "name": t["name"],
                    "description": t.get("description", t["name"]),
                    "endpoint": f"/{server.server_id}/{t['name']}"
                }
                for t in mcp_tools
            ]
        except Exception as e:
            print(f"Error fetching MCP tools from {server.server_id}: {e}")
            return [{"error": f"Could not fetch MCP tools from {server.server_id}: {e}"}]

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


async def execute_on_server(
    server: MCPServerConfig,
    tool_path: str,
    body: dict,
    tenant_ids: Optional[List[str]] = None,
    user_email: Optional[str] = None
) -> Any:
    """
    Execute a tool on any server based on its tier.

    US-011: Supports tenant-specific API keys AND dynamic endpoint routing.
    - If the user's tenant has a specific API key, it will be used
    - If the user's tenant has an endpoint override, requests route to different container

    Args:
        server: Server configuration
        tool_path: Path to the tool endpoint
        body: Request body
        tenant_ids: User's tenant/group IDs for API key and endpoint lookup
    """
    # US-011: Look up tenant-specific API key first, fall back to global env var
    api_key = None
    key_source = "default"

    if tenant_ids and server.api_key_env:
        # Try to get tenant-specific key from database
        tenant_keys = await get_tenant_api_keys_for_server(tenant_ids, server.server_id)
        if tenant_keys and server.api_key_env in tenant_keys:
            api_key = tenant_keys[server.api_key_env]
            key_source = f"tenant:{tenant_ids[0]}"
            print(f"  [TENANT-KEY] Using tenant-specific {server.api_key_env} for {server.server_id}")

    # Fall back to global environment variable
    if not api_key:
        api_key = os.getenv(server.api_key_env, "test-key") if server.api_key_env else "test-key"
        key_source = "env"

    # US-011: Dynamic endpoint routing - check for tenant-specific endpoint override
    endpoint_url = server.endpoint_url
    if tenant_ids:
        override_url = await get_tenant_endpoint_override(tenant_ids, server.server_id)
        if override_url:
            endpoint_url = override_url
            print(f"  [DYNAMIC-ROUTING] Routing {server.server_id} to {override_url} for tenant {tenant_ids}")

    # MCP Streamable HTTP: use JSON-RPC protocol instead of REST
    if server.tier == ServerTier.MCP_HTTP:
        clean_path = tool_path.strip("/")
        print(f"=== Executing MCP tool on {server.server_id} ===")
        print(f"  Tool: {clean_path}")
        print(f"  Key source: {key_source}")
        print(f"  Body: {body}")

        try:
            client = get_mcp_client(endpoint_url, api_key)
            result = await client.call_tool(clean_path, body)
            print(f"  MCP Response: OK")
            return result
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"MCP error on {server.server_id}/{clean_path}: {str(e)}"
            )

    # Build the full URL
    # For local servers, tool_path might already have leading slash
    clean_path = tool_path.strip("/")
    url = f"{endpoint_url}/{clean_path}"

    print(f"=== Executing on {server.server_id} ===")
    print(f"  Tier: {server.tier.value}")
    print(f"  URL: {url}")
    print(f"  Key source: {key_source}")
    print(f"  Body: {body}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            downstream_headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            # Forward the resolved end-user identity so per-user servers
            # (gmail, gdrive, calendar) load the right person's OAuth token
            # instead of falling back to default@local.
            if user_email:
                downstream_headers["X-User-Email"] = user_email
            response = await client.post(
                url,
                json=body,
                headers=downstream_headers
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


async def execute_tool_on_tenant(
    tenant_id: str,
    original_path: str,
    arguments: Dict[str, Any],
    tenant_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Execute a tool on the tenant's MCP server (supports both old TENANTS and new ALL_SERVERS)."""
    tenant = get_tenant(tenant_id)

    # Fallback: if not in old TENANTS dict, try ALL_SERVERS (for clickup, trello, sonarqube, etc.)
    if not tenant:
        server = get_server(tenant_id)
        if server and server.enabled:
            # US-011: Look up tenant-specific API key first
            api_key = None
            if tenant_ids and server.api_key_env:
                tenant_keys = await get_tenant_api_keys_for_server(tenant_ids, server.server_id)
                if tenant_keys and server.api_key_env in tenant_keys:
                    api_key = tenant_keys[server.api_key_env]
                    print(f"  [TENANT-KEY] Using tenant-specific key for {server.server_id}")

            # Fall back to global environment variable
            if not api_key:
                api_key = os.getenv(server.api_key_env, "test-key") if server.api_key_env else "test-key"

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    response = await client.post(
                        f"{server.endpoint_url}{original_path}",
                        json=arguments,
                        headers=headers
                    )
                    if response.status_code == 200:
                        return response.json()
                    else:
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=f"Server {tenant_id} returned: {response.text}"
                        )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
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

# Reserved paths that should NOT be treated as server IDs
RESERVED_PATHS = {"admin", "meta", "health", "servers", "refresh", "tenants", "tools", "debug", "openapi.json", "docs", "redoc", "portal"}


@app.get("/{server_id}")
async def get_server_tools(server_id: str, request: Request):
    """
    Get information and available tools for a specific server.

    Example: GET /github -> Returns list of GitHub tools
    """
    # Skip reserved paths
    if server_id in RESERVED_PATHS:
        raise HTTPException(status_code=404, detail=f"Use /{server_id}/* endpoints directly")

    # Check if this is a known server
    server = get_server(server_id)
    if not server:
        # Not a server, might be a debug endpoint or invalid
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_id}' not found. Use GET /servers for available servers."
        )

    # Check user access
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)
    has_access = await user_has_tenant_access_async(
        user.email, server_id, user.entra_groups)
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
    # Skip reserved paths (admin routes handled separately)
    if server_id in RESERVED_PATHS:
        raise HTTPException(
            status_code=404,
            detail=f"Reserved path '/{server_id}'. This should be handled by another route."
        )

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

    print(f"=== Tool Execution: /{server_id}/{tool_path} ===")

    # Identity comes from the authenticated headers and nowhere else. A
    # ?user_email= fallback used to stand here "for testing/demo": it let
    # anyone name themselves an MCP-Admin address and be believed, which
    # granted every server on the box.
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)

    has_access = await user_has_tenant_access_async(
        user.email, server_id, user.entra_groups)
    if not has_access:
        print(f"  ACCESS DENIED: {user.email} -> {server_id}")
        raise HTTPException(
            status_code=403,
            detail=f"User {user.email} does not have access to server '{server_id}'"
        )
    print(f"  ACCESS GRANTED: {user.email} -> {server_id}")

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

    # Get user's groups for dynamic routing and API key lookup (US-011)
    # We need GROUP names (like 'MCP-GitHub') not tenant/server IDs (like 'github')
    if user.entra_groups:
        user_groups = user.entra_groups
    else:
        # Look up groups from database
        from db import get_user_groups
        user_groups = await get_user_groups(user.email)
    print(f"  [ROUTING] User {user.email} groups for routing: {user_groups}")

    # Execute based on server tier
    return await execute_on_server(server, tool_path, body, user_groups, user_email=user.email)


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
    print(f"=== Legacy Tool Call: {tool_name} ===")

    # Refused before the cache is consulted, so 404-vs-403 cannot be used to
    # enumerate tools anonymously.
    user = await extract_user_from_headers_optional(request)
    require_identified(user.email if user else None)

    # Get tool info from cache
    tool_info = TOOLS_CACHE.get(tool_name)
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    tenant_id = tool_info["tenant_id"]
    original_path = tool_info["original_path"]

    has_access = await user_has_tenant_access_async(
        user.email, tenant_id, user.entra_groups)
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

    # Get user's tenant IDs for API key lookup (US-011)
    tenant_ids = await get_user_tenants_async(user.email, user.entra_groups)

    # Execute the tool
    result = await execute_tool_on_tenant(tenant_id, original_path, body, tenant_ids)
    return result
