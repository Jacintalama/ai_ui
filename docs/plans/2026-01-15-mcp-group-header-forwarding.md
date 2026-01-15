# MCP Group Header Forwarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Forward user's Open WebUI groups to MCP Proxy via HTTP headers so tools can be filtered by tenant membership.

**Architecture:** When Open WebUI connects to MCP servers, it will include an `X-OpenWebUI-User-Groups` header containing the user's group names (comma-separated). The MCP Proxy already reads this header and filters tools accordingly.

**Tech Stack:** Python, FastAPI, Open WebUI models

---

## Background

**The Problem:**
- Highspring employees (@highspring.com) need access to specific client tenant tools
- Entra ID groups (Tenant-Google, Tenant-AcmeCorp, etc.) determine which tools a user can access
- Open WebUI syncs these groups from OAuth tokens
- MCP Proxy is ready to filter tools by groups (reads X-User-Groups header)
- **GAP:** Open WebUI doesn't forward groups to MCP servers

**The Solution:**
1. Modify `include_user_info_headers()` to accept and include groups
2. In `middleware.py`, fetch user's groups and pass them when connecting to MCP servers

---

## Task 1: Update Headers Utility Function

**Files:**
- Modify: `backend/open_webui/utils/headers.py:1-11`

**Step 1: Read current implementation**

Current code at `backend/open_webui/utils/headers.py`:
```python
from urllib.parse import quote


def include_user_info_headers(headers, user):
    return {
        **headers,
        "X-OpenWebUI-User-Name": quote(user.name, safe=" "),
        "X-OpenWebUI-User-Id": user.id,
        "X-OpenWebUI-User-Email": user.email,
        "X-OpenWebUI-User-Role": user.role,
    }
```

**Step 2: Modify to accept optional groups parameter**

Replace entire file with:
```python
from urllib.parse import quote
from typing import Optional


def include_user_info_headers(headers, user, groups: Optional[list] = None):
    """
    Add user information headers to the request.

    Args:
        headers: Existing headers dict
        user: User model with name, id, email, role
        groups: Optional list of group names (for MCP server filtering)

    Returns:
        Updated headers dict with X-OpenWebUI-User-* headers
    """
    result = {
        **headers,
        "X-OpenWebUI-User-Name": quote(user.name, safe=" "),
        "X-OpenWebUI-User-Id": user.id,
        "X-OpenWebUI-User-Email": user.email,
        "X-OpenWebUI-User-Role": user.role,
    }

    # Add groups header if groups provided
    if groups:
        group_names = [g.name if hasattr(g, 'name') else str(g) for g in groups]
        result["X-OpenWebUI-User-Groups"] = ",".join(group_names)

    return result
```

**Step 3: Verify no breaking changes**

The function signature is backwards compatible - `groups` is optional with default `None`.
All existing callers pass only `(headers, user)` and will continue to work.

**Step 4: Commit**

```bash
cd "C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui"
git add backend/open_webui/utils/headers.py
git commit -m "feat: add optional groups parameter to include_user_info_headers

Adds X-OpenWebUI-User-Groups header when groups list is provided.
Backwards compatible - groups parameter is optional."
```

---

## Task 2: Forward Groups to MCP Servers in Middleware

**Files:**
- Modify: `backend/open_webui/utils/middleware.py:27-128` (imports section)
- Modify: `backend/open_webui/utils/middleware.py:1677-1722` (MCP connection section)

**Step 1: Add import for Groups model**

Find the imports section (around line 27-128). Add this import after the other model imports:

```python
from open_webui.models.groups import Groups
```

Also add import for the headers utility:

```python
from open_webui.utils.headers import include_user_info_headers
```

And add import for the env flag:

```python
from open_webui.env import ENABLE_FORWARD_USER_INFO_HEADERS
```

Note: Check if these are already imported. Only add if missing.

**Step 2: Find MCP connection code**

Locate the MCP server connection code around line 1677-1722. The section starts with:
```python
auth_type = mcp_server_connection.get("auth_type", "")
headers = {}
```

**Step 3: Modify to include user groups in headers**

Replace the headers building section (approximately lines 1677-1722) with:

```python
                    auth_type = mcp_server_connection.get("auth_type", "")
                    headers = {}
                    if auth_type == "bearer":
                        headers["Authorization"] = (
                            f"Bearer {mcp_server_connection.get('key', '')}"
                        )
                    elif auth_type == "none":
                        # No authentication
                        pass
                    elif auth_type == "session":
                        headers["Authorization"] = (
                            f"Bearer {request.state.token.credentials}"
                        )
                    elif auth_type == "system_oauth":
                        oauth_token = extra_params.get("__oauth_token__", None)
                        if oauth_token:
                            headers["Authorization"] = (
                                f"Bearer {oauth_token.get('access_token', '')}"
                            )
                    elif auth_type == "oauth_2.1":
                        try:
                            splits = server_id.split(":")
                            server_id = splits[-1] if len(splits) > 1 else server_id

                            oauth_token = await request.app.state.oauth_client_manager.get_oauth_token(
                                user.id, f"mcp:{server_id}"
                            )

                            if oauth_token:
                                headers["Authorization"] = (
                                    f"Bearer {oauth_token.get('access_token', '')}"
                                )
                        except Exception as e:
                            log.error(f"Error getting OAuth token: {e}")
                            oauth_token = None

                    # Add custom connection headers
                    connection_headers = mcp_server_connection.get("headers", None)
                    if connection_headers and isinstance(connection_headers, dict):
                        for key, value in connection_headers.items():
                            headers[key] = value

                    # Forward user info including groups to MCP server
                    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
                        try:
                            user_groups = Groups.get_groups_by_member_id(user.id)
                            headers = include_user_info_headers(headers, user, user_groups)
                        except Exception as e:
                            log.warning(f"Failed to get user groups for MCP headers: {e}")
                            headers = include_user_info_headers(headers, user)

                    mcp_clients[server_id] = MCPClient()
                    await mcp_clients[server_id].connect(
                        url=mcp_server_connection.get("url", ""),
                        headers=headers if headers else None,
                    )
```

**Step 4: Commit**

```bash
cd "C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui"
git add backend/open_webui/utils/middleware.py
git commit -m "feat: forward user groups to MCP servers via X-OpenWebUI-User-Groups header

When ENABLE_FORWARD_USER_INFO_HEADERS is enabled, MCP servers now receive:
- X-OpenWebUI-User-Name
- X-OpenWebUI-User-Id
- X-OpenWebUI-User-Email
- X-OpenWebUI-User-Role
- X-OpenWebUI-User-Groups (comma-separated group names)

This enables MCP Proxy to filter tools based on user's tenant group membership."
```

---

## Task 3: Verify MCP Proxy Compatibility

**Files:**
- Read: `C:\Users\alama\Desktop\Lukas Work\IO\mcp-proxy\auth.py`

**Step 1: Confirm MCP Proxy reads the correct header**

Your MCP Proxy should already handle these headers. Verify `auth.py` reads:
- `X-OpenWebUI-User-Groups` OR
- `X-User-Groups` OR
- `X-Entra-Groups`

If needed, add `X-OpenWebUI-User-Groups` to the list of accepted headers.

**Step 2: Test header parsing**

The MCP Proxy should parse comma-separated groups correctly:
```
X-OpenWebUI-User-Groups: Tenant-Google,Tenant-AcmeCorp
```

Should result in groups list: `["Tenant-Google", "Tenant-AcmeCorp"]`

---

## Task 4: Integration Testing

**Step 1: Set environment variable**

Ensure Open WebUI has:
```bash
ENABLE_FORWARD_USER_INFO_HEADERS=true
```

**Step 2: Test with a user who has groups**

1. Login as a user with Entra ID groups (e.g., steve@highspring.com with Tenant-Google group)
2. Open browser DevTools → Network tab
3. Trigger an MCP tool call (chat with a model that uses MCP tools)
4. Check the request headers to MCP Proxy
5. Verify `X-OpenWebUI-User-Groups: Tenant-Google` is present

**Step 3: Verify MCP Proxy filtering**

1. Check MCP Proxy logs for received groups
2. Verify only tools for Tenant-Google are returned
3. Test with user in multiple groups - should see tools from all assigned tenants

**Step 4: Document results**

Create test report at `docs/MULTITENANT-MCP-TEST-RESULTS.md`

---

## Task 5: Deploy to Kubernetes

**Step 1: Build and push updated Open WebUI image**

```bash
cd "C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui"
docker build -t your-registry/open-webui:v0.7.2-groups .
docker push your-registry/open-webui:v0.7.2-groups
```

**Step 2: Update Kubernetes deployment**

Update the image tag in your deployment or values file.

**Step 3: Ensure environment variable is set**

```bash
kubectl set env statefulset/open-webui -n open-webui \
  ENABLE_FORWARD_USER_INFO_HEADERS=true
```

**Step 4: Restart and verify**

```bash
kubectl rollout restart statefulset/open-webui -n open-webui
kubectl logs -f statefulset/open-webui -n open-webui
```

---

## Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Update headers.py with groups param | `utils/headers.py` |
| 2 | Forward groups in middleware.py | `utils/middleware.py` |
| 3 | Verify MCP Proxy compatibility | `mcp-proxy/auth.py` |
| 4 | Integration testing | Manual testing |
| 5 | Deploy to Kubernetes | Deployment configs |

## Flow After Implementation

```
steve@highspring.com logs in
         │
         ▼
   Entra ID OAuth
         │
         └── Token: groups=["Tenant-Google", "Tenant-AcmeCorp"]
         │
         ▼
   Open WebUI
         │
         ├── Syncs groups to DB
         │
         └── MCP Proxy Request Headers:
             X-OpenWebUI-User-Name: Steve
             X-OpenWebUI-User-Id: abc123
             X-OpenWebUI-User-Email: steve@highspring.com
             X-OpenWebUI-User-Role: user
             X-OpenWebUI-User-Groups: Tenant-Google,Tenant-AcmeCorp
         │
         ▼
   MCP Proxy
         │
         └── Filters tools by groups
         │
         ▼
   Steve sees ONLY:
   • Google tools (JIRA, Notion, GitHub)
   • AcmeCorp tools (JIRA, Slack)
```

---

*Plan Created: January 15, 2026*
