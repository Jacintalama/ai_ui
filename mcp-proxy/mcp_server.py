# mcp-proxy/mcp_server.py
"""
MCP Multi-Tenant Proxy Server using FastMCP

This server implements the MCP Streamable HTTP protocol, allowing Open WebUI
to connect to it natively with automatic user context forwarding.

Key Features:
- Native MCP Streamable HTTP transport
- Automatic user identification from MCP session
- Multi-tenant access control (user sees only their allowed tools)
- Dynamic tool routing to backend MCP servers

Open WebUI Connection:
1. Go to Admin Settings -> External Tools
2. Click "+ Add Server" and set Type to "MCP (Streamable HTTP)"
3. URL: http://mcp-proxy:8000/mcp
4. Auth: None (or Bearer with API key)

The user's email is automatically extracted from the MCP session context.
"""

import os
import json
import httpx
import jwt
from typing import Optional, Any
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError

from tenants import (
    ALL_SERVERS, MCPServerConfig, ServerTier,
    user_has_server_access, get_tenants_from_entra_groups,
    USER_TENANT_ACCESS
)
import db  # Database module for tenant access lookups


# =============================================================================
# CONFIGURATION
# =============================================================================

MCP_API_KEY = os.getenv("MCP_API_KEY", "test-key")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# Open WebUI JWT validation - REQUIRED for secure authentication
# This is the same key Open WebUI uses to sign its JWTs
WEBUI_SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", "")


def log(msg: str):
    """Debug logging."""
    if DEBUG:
        print(f"[MCP-PROXY] {msg}")


# =============================================================================
# OPEN WEBUI JWT VALIDATION
# =============================================================================

def validate_openwebui_jwt(token: str) -> dict:
    """
    Validate Open WebUI's JWT and extract user claims.

    Open WebUI sends JWTs signed with HS256 using WEBUI_SECRET_KEY.
    This provides secure, unforgeable user identification.

    Args:
        token: JWT from Authorization header

    Returns:
        dict with user claims (id, email, etc.)

    Raises:
        ValueError: If token is invalid or WEBUI_SECRET_KEY not configured
    """
    if not WEBUI_SECRET_KEY:
        raise ValueError("WEBUI_SECRET_KEY not configured - JWT validation disabled")

    try:
        # Debug: decode without verification to see token structure
        unverified = jwt.decode(token, options={"verify_signature": False})
        header = jwt.get_unverified_header(token)
        log(f"[JWT-DEBUG] Token header: {header}")
        log(f"[JWT-DEBUG] Token claims: {list(unverified.keys())}")
        log(f"[JWT-DEBUG] Using secret key (first 20 chars): {WEBUI_SECRET_KEY[:20]}...")

        # Decode and validate the JWT
        claims = jwt.decode(
            token,
            WEBUI_SECRET_KEY,
            algorithms=["HS256"]
        )
        log(f"[JWT] Valid token - claims: {list(claims.keys())}")
        return claims
    except jwt.ExpiredSignatureError:
        log("[JWT] Token expired")
        raise ValueError("Token expired")
    except jwt.InvalidTokenError as e:
        log(f"[JWT] Invalid token: {e}")
        raise ValueError(f"Invalid token: {e}")


def is_jwt_auth_configured() -> bool:
    """Check if JWT authentication is configured."""
    return bool(WEBUI_SECRET_KEY)


# =============================================================================
# FASTMCP SERVER INITIALIZATION
# =============================================================================

mcp = FastMCP(
    name="MCP Multi-Tenant Proxy",
    instructions="""
    This is a multi-tenant MCP proxy that routes tool calls to backend servers
    based on user access permissions.

    Available tool categories:
    - github_* : GitHub operations (repos, issues, PRs)
    - filesystem_* : File operations (read, write, list)
    - linear_* : Linear issue tracking
    - notion_* : Notion workspace

    Your access is determined by your user email. Use 'list_my_servers' to see
    what you have access to.
    """
)


# =============================================================================
# USER CONTEXT EXTRACTION
# =============================================================================

def get_auth_header_from_context(ctx: Context) -> Optional[str]:
    """Extract Authorization header from MCP context."""
    if hasattr(ctx, 'request_context') and ctx.request_context:
        request = getattr(ctx.request_context, 'request', None)
        if request:
            headers = getattr(request, 'headers', None)
            if headers and hasattr(headers, 'get'):
                return headers.get('Authorization') or headers.get('authorization')
    return None


async def get_user_info_from_context(ctx: Context) -> tuple[Optional[str], list[str]]:
    """
    Extract user email and tenants from MCP context.

    Authentication Flow (SECURE):
    1. Extract JWT from Authorization header
    2. Validate JWT signature using WEBUI_SECRET_KEY (cryptographically secure)
    3. If JWT valid, trust X-OpenWebUI-* headers for user info
    4. Lookup tenant access from database using email

    Security: Headers alone can be faked. JWT validation proves the request
    came from Open WebUI, making the headers trustworthy.

    Returns:
        Tuple of (email, tenants_list)
    """
    user_email = None
    user_tenants = []

    # Step 1: Get Authorization header
    auth_header = get_auth_header_from_context(ctx)

    if not auth_header or not auth_header.startswith("Bearer "):
        log("[AUTH] No Bearer token in Authorization header")
        return None, []

    token = auth_header.replace("Bearer ", "")

    # Step 2: Validate JWT using WEBUI_SECRET_KEY
    if not is_jwt_auth_configured():
        log("[AUTH] WEBUI_SECRET_KEY not configured - authentication disabled")
        return None, []

    try:
        # Validate the JWT - this proves the request came from Open WebUI
        jwt_claims = validate_openwebui_jwt(token)
        log(f"[JWT] Token validated successfully")

        # Step 3: Now we can trust the headers - get user email
        # The JWT proves this request came from Open WebUI, so headers are trustworthy
        user_email = _get_user_email_from_headers(ctx)

        if not user_email:
            # Fallback: try to get email from JWT claims directly
            user_email = jwt_claims.get("email") or jwt_claims.get("sub")
            if user_email:
                log(f"[JWT] Got email from JWT claims: {user_email}")

        if not user_email:
            log("[AUTH] JWT valid but no user email found")
            return None, []

        log(f"[AUTH] Authenticated user: {user_email}")

        # Step 4: Lookup tenant access from database
        user_tenants = await db.get_user_tenants(user_email)
        log(f"[DATABASE] User {user_email} has access to: {user_tenants}")

        return user_email, user_tenants

    except ValueError as e:
        log(f"[JWT] Validation failed: {e}")
        return None, []
    except Exception as e:
        log(f"[AUTH] Unexpected error: {e}")
        return None, []


def _get_user_email_from_headers(ctx: Context) -> Optional[str]:
    """
    Extract user email from X-OpenWebUI-User-Email header.

    SECURITY: Only call this AFTER validating the JWT!
    The JWT validation proves the request came from Open WebUI,
    making these headers trustworthy.
    """
    if hasattr(ctx, 'request_context') and ctx.request_context:
        request = getattr(ctx.request_context, 'request', None)
        if request:
            headers = getattr(request, 'headers', None)
            if headers and hasattr(headers, 'get'):
                email = headers.get('X-OpenWebUI-User-Email') or headers.get('x-openwebui-user-email')
                if email:
                    log(f"[HEADERS] Got email from X-OpenWebUI-User-Email: {email}")
                    return email
    return None


def _get_user_email_from_context(ctx: Context) -> Optional[str]:
    """
    Extract user email from MCP context (internal helper).

    Open WebUI's native MCP client forwards user information in the session.
    We can access it through ctx.request_context or ctx.meta.
    """
    # Debug: Log all context attributes
    log(f"=== SESSION AUTH DEBUG ===")
    log(f"Context type: {type(ctx)}")
    log(f"Context attributes: {[a for a in dir(ctx) if not a.startswith('_')]}")

    # CRITICAL: Check for Authorization header (OAuth token)
    if hasattr(ctx, 'request_context') and ctx.request_context:
        request = getattr(ctx.request_context, 'request', None)
        if request and hasattr(request, 'headers'):
            auth_header = request.headers.get('authorization') or request.headers.get('Authorization')
            if auth_header:
                log(f"[AUTH HEADER FOUND] Authorization: {auth_header[:50]}..." if len(str(auth_header)) > 50 else f"[AUTH HEADER FOUND] Authorization: {auth_header}")
                # Check if it's a Bearer token
                if auth_header.startswith('Bearer '):
                    token = auth_header[7:]
                    log(f"[BEARER TOKEN] Length: {len(token)} chars")
                    log(f"[BEARER TOKEN] First 100 chars: {token[:100]}...")
            else:
                log(f"[AUTH HEADER] No Authorization header found")
            # Log ALL headers for complete picture
            log(f"[ALL HEADERS] {dict(request.headers)}")

    # Try multiple ways to get user email
    user_email = None

    # Method 1: Check request context (headers)
    if hasattr(ctx, 'request_context') and ctx.request_context:
        log(f"request_context type: {type(ctx.request_context)}")
        log(f"request_context attrs: {[a for a in dir(ctx.request_context) if not a.startswith('_')]}")

        # Try to get headers - could be dict or object
        headers = getattr(ctx.request_context, 'headers', None)
        if headers:
            log(f"headers type: {type(headers)}")
            if isinstance(headers, dict):
                user_email = headers.get('X-OpenWebUI-User-Email') or headers.get('x-openwebui-user-email')
            else:
                user_email = getattr(headers, 'X-OpenWebUI-User-Email', None)
            if user_email:
                log(f"User email from headers: {user_email}")
                return user_email

        # Try request_context.request.headers (Starlette Request)
        request = getattr(ctx.request_context, 'request', None)
        if request:
            log(f"request type: {type(request)}")
            log(f"request attrs: {[a for a in dir(request) if not a.startswith('_')]}")
            req_headers = getattr(request, 'headers', None)
            if req_headers:
                log(f"req_headers type: {type(req_headers)}")
                # Starlette Headers object - use .get() method
                if hasattr(req_headers, 'get'):
                    user_email = req_headers.get('X-OpenWebUI-User-Email') or req_headers.get('x-openwebui-user-email')
                    if user_email:
                        log(f"User email from request.headers: {user_email}")
                        return user_email
                    # Log all headers for debugging
                    log(f"All request headers: {dict(req_headers)}")

        # Check for user_email directly on request_context
        user_email = getattr(ctx.request_context, 'user_email', None) or getattr(ctx.request_context, 'email', None)
        if user_email:
            log(f"User email from request_context: {user_email}")
            return user_email

    # Method 2: Check meta/client info (could be dict or object)
    if hasattr(ctx, 'meta') and ctx.meta:
        log(f"meta type: {type(ctx.meta)}")
        if isinstance(ctx.meta, dict):
            user_email = ctx.meta.get('user_email') or ctx.meta.get('email')
        else:
            user_email = getattr(ctx.meta, 'user_email', None) or getattr(ctx.meta, 'email', None)
        if user_email:
            log(f"User email from meta: {user_email}")
            return user_email

    # Method 3: Check client info
    if hasattr(ctx, 'client_info') and ctx.client_info:
        log(f"client_info type: {type(ctx.client_info)}")
        user_email = getattr(ctx.client_info, 'email', None) or getattr(ctx.client_info, 'user_email', None)
        if user_email:
            log(f"User email from client_info: {user_email}")
            return user_email

    # Method 4: Check session data (could be object, not dict)
    if hasattr(ctx, 'session') and ctx.session:
        log(f"session type: {type(ctx.session)}")
        log(f"session attrs: {[a for a in dir(ctx.session) if not a.startswith('_')]}")

        if isinstance(ctx.session, dict):
            user_email = ctx.session.get('user_email')
        else:
            # It's an object - try various attributes
            user_email = getattr(ctx.session, 'user_email', None)
            if not user_email:
                user_email = getattr(ctx.session, 'email', None)
            # Try _meta or meta on session
            session_meta = getattr(ctx.session, '_meta', None) or getattr(ctx.session, 'meta', None)
            if session_meta and not user_email:
                if isinstance(session_meta, dict):
                    user_email = session_meta.get('user_email') or session_meta.get('email')
                else:
                    user_email = getattr(session_meta, 'user_email', None) or getattr(session_meta, 'email', None)
        if user_email:
            log(f"User email from session: {user_email}")
            return user_email

    # Method 5: Check for state on context
    if hasattr(ctx, 'state') and ctx.state:
        log(f"state type: {type(ctx.state)}")
        if isinstance(ctx.state, dict):
            user_email = ctx.state.get('user_email') or ctx.state.get('email')
        else:
            user_email = getattr(ctx.state, 'user_email', None) or getattr(ctx.state, 'email', None)
        if user_email:
            log(f"User email from state: {user_email}")
            return user_email

    log("No user email found in context - full debug:")
    # Log all attributes for debugging
    for attr in dir(ctx):
        if not attr.startswith('_'):
            try:
                val = getattr(ctx, attr)
                if not callable(val):
                    log(f"  ctx.{attr} = {type(val).__name__}: {str(val)[:100]}")
            except Exception as e:
                log(f"  ctx.{attr} = ERROR: {e}")

    return None


def get_user_servers(user_email: Optional[str], user_groups: list[str] = None) -> list[str]:
    """Get list of server IDs the user has access to."""
    if not user_email:
        log("No user email, returning empty server list")
        return []

    servers = []
    for server_id in ALL_SERVERS.keys():
        if user_has_server_access(user_email, server_id, user_groups):
            servers.append(server_id)

    log(f"User {user_email} (groups={user_groups}) has access to: {servers}")
    return servers


# =============================================================================
# CORE TOOLS - Always Available
# =============================================================================

@mcp.tool
async def list_my_servers(ctx: Context) -> str:
    """
    List all MCP servers you have access to based on your permissions.

    Returns a formatted list showing:
    - Server ID and display name
    - Server tier (local, http, sse, stdio)
    - Description
    - Whether it's enabled

    Use this to discover what tools are available to you.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_email:
        return """Unable to identify user.

If you're using Open WebUI:
1. Make sure you're logged in
2. Connect via Admin Settings -> External Tools -> MCP (Streamable HTTP)
3. URL: http://mcp-proxy:8000/mcp

Your user email should be automatically forwarded."""

    allowed_servers = get_user_servers(user_email, user_groups)

    if not allowed_servers:
        return f"No servers available for {user_email}. Contact admin for access."

    result = f"## Available Servers for {user_email}\n\n"
    result += f"**Total:** {len(allowed_servers)} server(s)\n\n"

    for server_id in allowed_servers:
        server = ALL_SERVERS.get(server_id)
        if server:
            status = "Enabled" if server.enabled else "Disabled"
            result += f"### {server.display_name} (`{server_id}`)\n"
            result += f"- **Tier:** {server.tier.value}\n"
            result += f"- **Status:** {status}\n"
            result += f"- **Description:** {server.description}\n"
            result += f"- **Tools:** Use `{server_id}_*` prefix\n\n"

    return result


@mcp.tool
async def check_my_access(ctx: Context) -> str:
    """
    Check your current user identity and access permissions.

    Returns:
    - Your identified email
    - List of servers you can access
    - Your access level for each
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_email:
        return "User not identified. Please ensure you're logged into Open WebUI."

    # Get detailed access info from database (user_groups contains tenant_ids from DB)
    access_info = []
    for tenant_id in user_groups:
        # Look up access level from database
        access_level = await db.get_user_access_level(user_email, tenant_id)
        access_info.append({
            "server": tenant_id,
            "level": access_level or "read"
        })

    result = f"## Access Report for {user_email}\n\n"

    if not access_info:
        result += "No explicit access configured. Contact admin.\n"
    else:
        result += "| Server | Access Level |\n"
        result += "|--------|-------------|\n"
        for info in access_info:
            result += f"| {info['server']} | {info['level']} |\n"

    return result


# =============================================================================
# PROXY TOOL EXECUTION
# =============================================================================

async def execute_on_backend(server: MCPServerConfig, tool_name: str, args: dict) -> Any:
    """Execute a tool on a backend MCP server."""
    api_key = os.getenv(server.api_key_env, MCP_API_KEY) if server.api_key_env else MCP_API_KEY
    url = f"{server.endpoint_url}/{tool_name}"

    log(f"Executing {tool_name} on {server.server_id}: {url}")
    log(f"Args: {json.dumps(args)[:200]}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=args,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            log(f"Response: {response.status_code}")

            if response.status_code == 200:
                return response.json()
            else:
                raise ToolError(f"Backend error ({response.status_code}): {response.text[:500]}")

    except httpx.TimeoutException:
        raise ToolError(f"Timeout connecting to {server.display_name}")
    except Exception as e:
        raise ToolError(f"Error: {str(e)}")


# =============================================================================
# GITHUB TOOLS (when user has 'github' access)
# =============================================================================

@mcp.tool
async def github_search_repositories(
    ctx: Context,
    query: str
) -> str:
    """
    Search GitHub repositories.

    Args:
        query: Search query (e.g., "kubernetes", "machine learning python")

    Returns:
        List of matching repositories with stars and descriptions.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "github", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access GitHub server")

    server = ALL_SERVERS["github"]
    result = await execute_on_backend(server, "search_repositories", {"query": query})

    # Format the result nicely
    if isinstance(result, dict):
        return json.dumps(result, indent=2)[:3000]
    return str(result)[:3000]


@mcp.tool
async def github_list_repos(
    ctx: Context,
    username: Optional[str] = None
) -> str:
    """
    List GitHub repositories for a user.

    Args:
        username: GitHub username (optional, defaults to authenticated user)

    Returns:
        List of repositories.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "github", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access GitHub server")

    server = ALL_SERVERS["github"]
    args = {"username": username} if username else {}
    result = await execute_on_backend(server, "list_repositories", args)

    return json.dumps(result, indent=2)[:3000] if isinstance(result, dict) else str(result)[:3000]


@mcp.tool
async def github_get_file(
    ctx: Context,
    owner: str,
    repo: str,
    path: str
) -> str:
    """
    Get contents of a file from a GitHub repository.

    Args:
        owner: Repository owner (username or org)
        repo: Repository name
        path: File path within the repository

    Returns:
        File contents.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "github", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access GitHub server")

    server = ALL_SERVERS["github"]
    result = await execute_on_backend(server, "get_file_contents", {
        "owner": owner,
        "repo": repo,
        "path": path
    })

    return json.dumps(result, indent=2)[:5000] if isinstance(result, dict) else str(result)[:5000]


# =============================================================================
# FILESYSTEM TOOLS (when user has 'filesystem' access)
# =============================================================================

@mcp.tool
async def filesystem_list_directory(
    ctx: Context,
    path: str = "/data"
) -> str:
    """
    List files and directories in a path.

    Args:
        path: Directory path to list (default: /data)

    Returns:
        List of files and directories.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "filesystem", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access Filesystem server")

    server = ALL_SERVERS["filesystem"]
    result = await execute_on_backend(server, "list_directory", {"path": path})

    return json.dumps(result, indent=2)[:3000] if isinstance(result, dict) else str(result)[:3000]


@mcp.tool
async def filesystem_read_file(
    ctx: Context,
    path: str
) -> str:
    """
    Read contents of a file.

    Args:
        path: Full path to the file

    Returns:
        File contents.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "filesystem", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access Filesystem server")

    server = ALL_SERVERS["filesystem"]
    result = await execute_on_backend(server, "read_file", {"path": path})

    return json.dumps(result, indent=2)[:5000] if isinstance(result, dict) else str(result)[:5000]


@mcp.tool
async def filesystem_write_file(
    ctx: Context,
    path: str,
    content: str
) -> str:
    """
    Write content to a file.

    Args:
        path: Full path to the file
        content: Content to write

    Returns:
        Confirmation message.
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    if not user_has_server_access(user_email, "filesystem", user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access Filesystem server")

    server = ALL_SERVERS["filesystem"]
    result = await execute_on_backend(server, "write_file", {"path": path, "content": content})

    return f"File written successfully: {path}"


# =============================================================================
# GENERIC TOOL EXECUTION (for any server)
# =============================================================================

@mcp.tool
async def execute_tool(
    ctx: Context,
    server_id: str,
    tool_name: str,
    arguments: str = "{}"
) -> str:
    """
    Execute any MCP tool on any server you have access to.

    Args:
        server_id: Server ID (e.g., 'github', 'filesystem', 'linear')
        tool_name: Tool name (e.g., 'search_repositories', 'list_directory')
        arguments: JSON string of arguments (e.g., '{"query": "mcp"}')

    Returns:
        Tool execution result.

    Example:
        execute_tool("github", "search_repositories", '{"query": "kubernetes"}')
    """
    user_email, user_groups = await get_user_info_from_context(ctx)

    # Check access
    if not user_has_server_access(user_email, server_id, user_groups):
        raise ToolError(f"Access Denied: {user_email} cannot access server '{server_id}'")

    # Get server config
    server = ALL_SERVERS.get(server_id)
    if not server:
        raise ToolError(f"Server '{server_id}' not found")

    if not server.enabled:
        raise ToolError(f"Server '{server_id}' is disabled")

    # Parse arguments
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        raise ToolError(f"Invalid JSON arguments: {arguments}")

    # Execute
    result = await execute_on_backend(server, tool_name, args)

    return json.dumps(result, indent=2)[:5000] if isinstance(result, dict) else str(result)[:5000]


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys

    # Default to HTTP transport for Open WebUI native MCP
    transport = os.getenv("MCP_TRANSPORT", "http")
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    print(f"Starting MCP Multi-Tenant Proxy...")
    print(f"Transport: {transport}")
    print(f"Host: {host}:{port}")
    print(f"Endpoint: http://{host}:{port}/mcp")
    print(f"Servers configured: {len(ALL_SERVERS)}")

    # Run the server
    mcp.run(
        transport=transport,
        host=host,
        port=port
    )
