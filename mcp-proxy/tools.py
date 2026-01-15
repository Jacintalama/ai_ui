# mcp-proxy/tools.py
import httpx
from typing import List, Dict, Any
from tenants import TenantConfig

async def fetch_tools_from_mcp(tenant: TenantConfig) -> List[Dict[str, Any]]:
    """Fetch available tools from a tenant's MCP server."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # mcpo exposes OpenAPI at /openapi.json
            response = await client.get(
                f"{tenant.mcp_endpoint}/openapi.json",
                headers={"Authorization": f"Bearer {tenant.mcp_api_key}"}
            )
            if response.status_code != 200:
                return []

            openapi = response.json()
            tools = []

            # Extract tools from OpenAPI paths
            for path, methods in openapi.get("paths", {}).items():
                if path in ["/health", "/docs", "/openapi.json", "/redoc"]:
                    continue

                for method, spec in methods.items():
                    if method.lower() == "post":
                        tool_name = path.strip("/").replace("/", "_")
                        tools.append({
                            "name": f"{tenant.tenant_id}_{tool_name}",
                            "original_name": tool_name,
                            "tenant_id": tenant.tenant_id,
                            "tenant_name": tenant.display_name,
                            "description": spec.get("summary", spec.get("description", "")),
                            "path": path,
                            "method": method.upper()
                        })

            return tools
    except Exception as e:
        print(f"Error fetching tools from {tenant.tenant_id}: {e}")
        return []

async def get_tools_for_user(tenants: List[TenantConfig]) -> List[Dict[str, Any]]:
    """Get all tools available to a user based on their tenant access."""
    all_tools = []
    for tenant in tenants:
        tools = await fetch_tools_from_mcp(tenant)
        all_tools.extend(tools)
    return all_tools


async def execute_tool(
    tenant: TenantConfig,
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute a tool on the tenant's MCP server with injected credentials."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Build headers with tenant credentials
            headers = {
                "Authorization": f"Bearer {tenant.mcp_api_key}",
                "Content-Type": "application/json"
            }

            # Inject tenant-specific credentials into request
            for key, value in tenant.credentials.items():
                headers[f"X-Tenant-{key}"] = value

            response = await client.post(
                f"{tenant.mcp_endpoint}/{tool_name}",
                json=arguments,
                headers=headers
            )

            return {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "result": response.json() if response.status_code == 200 else None,
                "error": response.text if response.status_code != 200 else None
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
