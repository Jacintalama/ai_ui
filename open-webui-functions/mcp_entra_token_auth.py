"""
MCP Entra ID Token Authentication Function for Open WebUI

This function implements Lukas's preferred authentication method:
- Uses __oauth_token__ to get the actual Entra ID token (NOT headers)
- Decodes JWT to extract groups claim directly from token
- Groups determine MCP server access (multi-tenant)

WHY THIS IS BETTER THAN HEADERS:
- Token is cryptographically signed by Entra ID (can't be faked)
- Groups come from identity provider, not client headers
- "Unified" authentication as Lukas requested

REQUIREMENTS:
- Open WebUI configured with Entra ID OAuth/OIDC
- ENABLE_OAUTH_GROUP_MANAGEMENT=true (optional but helps)
- Entra ID app configured to include groups claim in tokens
  (Azure Portal > App Registration > Token Configuration > Add groups claim)

INSTALLATION:
1. Go to Open WebUI Admin Panel -> Workspace -> Functions
2. Click "+" to add new function
3. Paste this ENTIRE code
4. Click "Save"
5. Enable this function for your model

TOKEN STRUCTURE (what we extract):
- id_token or access_token contains:
  - "groups": ["group-id-1", "group-id-2", ...]  (Azure AD group object IDs)
  - "email" or "preferred_username": user email
  - "name": display name
  - "oid": user object ID
"""

import httpx
import json
import base64
from typing import Optional, Callable, Any, List
from pydantic import BaseModel, Field


def decode_jwt_payload(token: str) -> dict:
    """
    Decode JWT payload without verification (verification done by Open WebUI).
    We trust the token because Open WebUI already validated it with the IdP.

    :param token: JWT token string
    :return: Decoded payload as dict
    """
    try:
        # JWT format: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return {}

        # Decode payload (second part)
        payload_b64 = parts[1]
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_json = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_json)
    except Exception as e:
        print(f"[MCP-EntraAuth] Error decoding JWT: {e}")
        return {}


class Tools:
    """
    MCP Tools with Entra ID Token Authentication

    Uses __oauth_token__ parameter to get the actual Entra ID token,
    extracts groups from token claims, and enforces multi-tenant access.
    """

    class Valves(BaseModel):
        """Configuration for the MCP Entra Token Auth Function."""
        MCP_PROXY_URL: str = Field(
            default="http://mcp-proxy:8000",
            description="URL of the MCP Proxy Gateway"
        )
        TIMEOUT_SECONDS: int = Field(
            default=30,
            description="Request timeout in seconds"
        )
        # Entra ID group ID to friendly name mapping (optional)
        # You can add your Azure AD group object IDs here
        GROUP_ID_MAPPING: str = Field(
            default="{}",
            description="JSON mapping of Azure group IDs to names (e.g., {'guid': 'Tenant-Google'})"
        )

    def __init__(self):
        self.valves = self.Valves()

    def _extract_user_from_token(self, oauth_token: Optional[dict]) -> dict:
        """
        Extract user information from the Entra ID OAuth token.

        :param oauth_token: Dict containing access_token, id_token, etc.
        :return: Dict with email, name, groups extracted from token
        """
        if not oauth_token:
            print("[MCP-EntraAuth] No oauth_token provided")
            return {"email": "", "name": "", "groups": [], "oid": "", "token_source": "none"}

        # Try id_token first (usually has more user claims), then access_token
        token_to_decode = oauth_token.get("id_token") or oauth_token.get("access_token")

        if not token_to_decode:
            print("[MCP-EntraAuth] No id_token or access_token in oauth_token")
            print(f"[MCP-EntraAuth] oauth_token keys: {list(oauth_token.keys())}")
            return {"email": "", "name": "", "groups": [], "oid": "", "token_source": "none"}

        # Decode the JWT payload
        payload = decode_jwt_payload(token_to_decode)

        if not payload:
            print("[MCP-EntraAuth] Failed to decode token payload")
            return {"email": "", "name": "", "groups": [], "oid": "", "token_source": "decode_failed"}

        # Extract user info from claims
        # Entra ID uses different claim names depending on token type
        email = (
            payload.get("email") or
            payload.get("preferred_username") or
            payload.get("upn") or  # User Principal Name
            ""
        )

        name = (
            payload.get("name") or
            payload.get("given_name", "") + " " + payload.get("family_name", "") or
            email.split("@")[0] if email else ""
        )

        # Groups claim - contains Azure AD group object IDs
        groups = payload.get("groups", [])

        # Check for groups overage (too many groups, need Graph API call)
        has_groups_overage = "_claim_names" in payload and "groups" in payload.get("_claim_names", {})
        if has_groups_overage:
            print("[MCP-EntraAuth] WARNING: Groups overage detected. User has >200 groups.")
            print("[MCP-EntraAuth] Groups not included in token. Would need Graph API call.")

        # Map group IDs to friendly names if mapping configured
        try:
            group_mapping = json.loads(self.valves.GROUP_ID_MAPPING)
            if group_mapping and groups:
                mapped_groups = []
                for g in groups:
                    if g in group_mapping:
                        mapped_groups.append(group_mapping[g])
                    else:
                        mapped_groups.append(g)  # Keep original ID if no mapping
                groups = mapped_groups
        except json.JSONDecodeError:
            pass  # Keep original groups if mapping is invalid

        user_info = {
            "email": email,
            "name": name.strip(),
            "groups": groups,
            "oid": payload.get("oid", ""),  # Object ID
            "tid": payload.get("tid", ""),  # Tenant ID
            "token_source": "id_token" if oauth_token.get("id_token") else "access_token",
            "has_groups_overage": has_groups_overage,
        }

        print(f"[MCP-EntraAuth] Extracted user: {email}, groups: {len(groups)}, source: {user_info['token_source']}")

        return user_info

    def _build_headers(self, user_info: dict) -> dict:
        """
        Build headers for MCP Proxy request with user info from token.

        :param user_info: User info extracted from Entra ID token
        :return: Headers dict for MCP Proxy
        """
        groups_str = ",".join(user_info.get("groups", []))

        return {
            "X-OpenWebUI-User-Email": user_info.get("email", ""),
            "X-OpenWebUI-User-Name": user_info.get("name", ""),
            "X-OpenWebUI-User-Groups": groups_str,
            "X-User-Groups": groups_str,
            "X-Entra-Groups": groups_str,
            "X-Entra-OID": user_info.get("oid", ""),
            "X-Entra-TID": user_info.get("tid", ""),
            "X-Auth-Source": "entra-token",  # Indicates auth came from token, not headers
            "Content-Type": "application/json",
        }

    async def debug_oauth_token(
        self,
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Debug tool to inspect your OAuth token and extracted claims.
        Use this to verify Entra ID groups are being passed correctly via token.

        :return: Token information and extracted claims
        """
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Inspecting OAuth token...", "done": False}
            })

        result = "## OAuth Token Debug\n\n"

        # Check if __oauth_token__ is available
        if not __oauth_token__:
            result += "**__oauth_token__ is NOT available!**\n\n"
            result += "This means:\n"
            result += "- Open WebUI may not be configured for OAuth/OIDC\n"
            result += "- Or the user is not logged in via OAuth\n"
            result += "- Or the token refresh failed\n\n"
            result += "### Fallback: __user__ context\n\n"
            result += f"```json\n{json.dumps(__user__, indent=2, default=str)}\n```\n"

            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": "No OAuth token found", "done": True}
                })
            return result

        # Show what keys are in oauth_token
        result += "### OAuth Token Keys\n\n"
        result += f"```json\n{json.dumps(list(__oauth_token__.keys()), indent=2)}\n```\n\n"

        # Extract and show user info from token
        user_info = self._extract_user_from_token(__oauth_token__)

        result += "### Extracted User Info (from token claims)\n\n"
        result += f"- **Email:** {user_info.get('email', 'N/A')}\n"
        result += f"- **Name:** {user_info.get('name', 'N/A')}\n"
        result += f"- **Object ID (oid):** {user_info.get('oid', 'N/A')}\n"
        result += f"- **Tenant ID (tid):** {user_info.get('tid', 'N/A')}\n"
        result += f"- **Token Source:** {user_info.get('token_source', 'N/A')}\n"
        result += f"- **Groups Overage:** {user_info.get('has_groups_overage', False)}\n\n"

        # Show groups
        groups = user_info.get("groups", [])
        result += f"### Groups ({len(groups)})\n\n"
        if groups:
            for g in groups[:20]:  # Show first 20
                result += f"- `{g}`\n"
            if len(groups) > 20:
                result += f"\n_...and {len(groups) - 20} more groups_\n"
        else:
            result += "_No groups found in token._\n\n"
            result += "**To include groups in Entra ID tokens:**\n"
            result += "1. Go to Azure Portal > App Registrations > Your App\n"
            result += "2. Go to Token Configuration\n"
            result += "3. Click 'Add groups claim'\n"
            result += "4. Select the group types to include\n"

        # Compare with __user__ context
        result += "\n### Comparison with __user__ context\n\n"
        user_groups = __user__.get("groups", [])
        result += f"- **__user__ groups:** {len(user_groups) if isinstance(user_groups, list) else 'N/A'}\n"
        result += f"- **Token groups:** {len(groups)}\n"

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Found {len(groups)} groups in token", "done": True}
            })

        return result

    async def list_my_servers(
        self,
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List all MCP servers you have access to based on your Entra ID groups.
        Uses the OAuth token to determine group membership.

        :return: List of available MCP servers
        """
        # Extract user from token (preferred) or fall back to __user__
        if __oauth_token__:
            user_info = self._extract_user_from_token(__oauth_token__)
        else:
            # Fallback to __user__ if no token
            user_info = {
                "email": __user__.get("email", ""),
                "name": __user__.get("name", ""),
                "groups": __user__.get("groups", []),
                "token_source": "fallback_user_context"
            }

        user_email = user_info.get("email", "unknown")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Checking access for {user_email}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.get(
                    f"{self.valves.MCP_PROXY_URL}/servers",
                    headers=self._build_headers(user_info)
                )

                if response.status_code == 200:
                    data = response.json()
                    servers = data.get("servers", [])

                    auth_method = "Entra ID Token" if __oauth_token__ else "Fallback (headers)"

                    result = f"## Available MCP Servers\n\n"
                    result += f"**User:** {user_email}\n"
                    result += f"**Auth Method:** {auth_method}\n"
                    result += f"**Groups:** {len(user_info.get('groups', []))}\n"
                    result += f"**Servers:** {len(servers)}\n\n"

                    if not servers:
                        result += "_No servers available. Your Entra ID groups may not have MCP access._\n"
                        return result

                    for server in servers:
                        status = "Enabled" if server.get("enabled", True) else "Disabled"
                        result += f"### {server['name']} (`{server['id']}`)\n"
                        result += f"- Status: {status}\n"
                        result += f"- {server.get('description', 'No description')}\n\n"

                    if __event_emitter__:
                        await __event_emitter__({
                            "type": "status",
                            "data": {"description": f"Found {len(servers)} servers", "done": True}
                        })

                    return result
                else:
                    return f"Error: {response.status_code} - {response.text}"

        except Exception as e:
            return f"Error connecting to MCP Proxy: {str(e)}"

    async def execute_mcp_tool(
        self,
        server: str,
        tool: str,
        arguments: str = "{}",
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Execute any MCP tool with Entra ID token authentication.

        :param server: Server ID (e.g., 'github', 'filesystem')
        :param tool: Tool name (e.g., 'search_repositories', 'list_directory')
        :param arguments: JSON string of arguments
        :return: Tool execution result
        """
        # Extract user from token
        if __oauth_token__:
            user_info = self._extract_user_from_token(__oauth_token__)
        else:
            user_info = {
                "email": __user__.get("email", ""),
                "groups": __user__.get("groups", []),
                "token_source": "fallback"
            }

        user_email = user_info.get("email", "unknown")

        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Executing {server}/{tool}...", "done": False}
            })

        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"Error: Invalid JSON arguments: {arguments}"

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.valves.MCP_PROXY_URL}/{server}/{tool}",
                    json=args_dict,
                    headers=self._build_headers(user_info)
                )

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"Completed {server}/{tool}", "done": True}
                    })

                if response.status_code == 200:
                    try:
                        data = response.json()
                        return f"**Result:**\n```json\n{json.dumps(data, indent=2)[:3000]}\n```"
                    except:
                        return f"**Result:**\n```\n{response.text[:3000]}\n```"
                elif response.status_code == 403:
                    return f"**Access Denied:** Your Entra ID groups don't have access to '{server}'."
                elif response.status_code == 404:
                    return f"**Not Found:** Server '{server}' or tool '{tool}' doesn't exist."
                else:
                    return f"**Error ({response.status_code}):** {response.text}"

        except Exception as e:
            return f"Error: {str(e)}"

    async def github_search(
        self,
        query: str,
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Search GitHub repositories. Requires GitHub server access via Entra ID groups.

        :param query: Search query (e.g., "kubernetes", "machine learning")
        :return: List of matching repositories
        """
        return await self.execute_mcp_tool(
            server="github",
            tool="search_repositories",
            arguments=json.dumps({"query": query}),
            __oauth_token__=__oauth_token__,
            __user__=__user__,
            __event_emitter__=__event_emitter__
        )

    async def list_files(
        self,
        path: str = "/data",
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        List files in a directory. Requires Filesystem server access via Entra ID groups.

        :param path: Directory path to list
        :return: List of files and directories
        """
        return await self.execute_mcp_tool(
            server="filesystem",
            tool="list_directory",
            arguments=json.dumps({"path": path}),
            __oauth_token__=__oauth_token__,
            __user__=__user__,
            __event_emitter__=__event_emitter__
        )

    async def read_file(
        self,
        path: str,
        __oauth_token__: Optional[dict] = None,
        __user__: dict = {},
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Read file contents. Requires Filesystem server access via Entra ID groups.

        :param path: Full path to the file
        :return: File contents
        """
        return await self.execute_mcp_tool(
            server="filesystem",
            tool="read_file",
            arguments=json.dumps({"path": path}),
            __oauth_token__=__oauth_token__,
            __user__=__user__,
            __event_emitter__=__event_emitter__
        )
