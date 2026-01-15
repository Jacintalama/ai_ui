# MCP Proxy Gateway Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a multi-tenant MCP proxy gateway that filters tools and injects credentials based on user's tenant membership.

**Architecture:** FastAPI service sits between Open WebUI and per-tenant MCP servers. Extracts user identity from `X-OpenWebUI-User-Email` header, queries PostgreSQL for tenant memberships, filters available tools, and injects tenant-specific credentials before forwarding to the correct MCP backend.

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL, Docker, mcpo, httpx

---

## Prerequisites

Before starting, ensure:
- Docker Desktop is running
- Open WebUI is running on port 3000
- MCP Filesystem server is running on port 8001 (from Phase 1)

---

## Task 1: Create Project Structure

**Files:**
- Create: `mcp-proxy/requirements.txt`
- Create: `mcp-proxy/main.py`
- Create: `mcp-proxy/.env.example`

**Step 1: Create directory structure**

```bash
mkdir -p mcp-proxy
cd mcp-proxy
```

**Step 2: Create requirements.txt**

```text
fastapi==0.115.0
uvicorn==0.32.0
httpx==0.27.0
asyncpg==0.29.0
pydantic==2.9.0
pydantic-settings==2.5.0
python-dotenv==1.0.1
```

**Step 3: Create minimal FastAPI app**

```python
# mcp-proxy/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(
    title="MCP Proxy Gateway",
    description="Multi-tenant MCP proxy for Open WebUI",
    version="0.1.0"
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mcp-proxy"}

@app.get("/")
async def root():
    return {"message": "MCP Proxy Gateway", "docs": "/docs"}
```

**Step 4: Create .env.example**

```bash
# mcp-proxy/.env.example
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mcpproxy
DEBUG=true
```

**Step 5: Test locally**

```bash
cd mcp-proxy
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Visit http://localhost:8000/health
# Expected: {"status": "healthy", "service": "mcp-proxy"}
```

**Step 6: Commit**

```bash
cd ..
git add mcp-proxy/
git commit -m "feat(proxy): create FastAPI skeleton with health endpoint"
```

---

## Task 2: Add User Extraction from Headers

**Files:**
- Modify: `mcp-proxy/main.py`
- Create: `mcp-proxy/auth.py`

**Step 1: Create auth module**

```python
# mcp-proxy/auth.py
from fastapi import Request, HTTPException
from typing import Optional
from dataclasses import dataclass

@dataclass
class UserInfo:
    """User information extracted from Open WebUI headers."""
    email: str
    user_id: str
    name: str
    role: str
    chat_id: Optional[str] = None

def extract_user_from_headers(request: Request) -> UserInfo:
    """
    Extract user info from X-OpenWebUI-* headers.

    Open WebUI sends these headers when ENABLE_FORWARD_USER_INFO_HEADERS=true:
    - X-OpenWebUI-User-Email
    - X-OpenWebUI-User-Id
    - X-OpenWebUI-User-Name
    - X-OpenWebUI-User-Role
    - X-OpenWebUI-Chat-Id
    """
    email = request.headers.get("X-OpenWebUI-User-Email")
    user_id = request.headers.get("X-OpenWebUI-User-Id", "")
    name = request.headers.get("X-OpenWebUI-User-Name", "")
    role = request.headers.get("X-OpenWebUI-User-Role", "user")
    chat_id = request.headers.get("X-OpenWebUI-Chat-Id")

    if not email:
        raise HTTPException(
            status_code=401,
            detail="Missing X-OpenWebUI-User-Email header. Ensure ENABLE_FORWARD_USER_INFO_HEADERS=true in Open WebUI."
        )

    return UserInfo(
        email=email,
        user_id=user_id,
        name=name,
        role=role,
        chat_id=chat_id
    )
```

**Step 2: Add debug endpoint to main.py**

```python
# mcp-proxy/main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from auth import extract_user_from_headers, UserInfo

app = FastAPI(
    title="MCP Proxy Gateway",
    description="Multi-tenant MCP proxy for Open WebUI",
    version="0.1.0"
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mcp-proxy"}

@app.get("/")
async def root():
    return {"message": "MCP Proxy Gateway", "docs": "/docs"}

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
```

**Step 3: Test header extraction**

```bash
# Test without headers (should fail)
curl http://localhost:8000/debug/user
# Expected: {"detail": "Missing X-OpenWebUI-User-Email header..."}

# Test with headers (should succeed)
curl -H "X-OpenWebUI-User-Email: john@company.com" \
     -H "X-OpenWebUI-User-Name: John Doe" \
     http://localhost:8000/debug/user
# Expected: {"email": "john@company.com", "name": "John Doe", ...}
```

**Step 4: Commit**

```bash
git add mcp-proxy/
git commit -m "feat(proxy): add user extraction from X-OpenWebUI headers"
```

---

## Task 3: Add In-Memory Tenant Configuration

**Files:**
- Create: `mcp-proxy/tenants.py`
- Modify: `mcp-proxy/main.py`

**Step 1: Create tenant management module**

```python
# mcp-proxy/tenants.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class TenantConfig:
    """Configuration for a tenant."""
    tenant_id: str
    display_name: str
    mcp_endpoint: str
    mcp_api_key: str
    credentials: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True

@dataclass
class UserTenantAccess:
    """User's access to a tenant."""
    user_email: str
    tenant_id: str
    access_level: str = "read"  # read, write, admin

# In-memory storage (will be replaced with PostgreSQL in Task 5)
TENANTS: Dict[str, TenantConfig] = {
    "google": TenantConfig(
        tenant_id="google",
        display_name="Google",
        mcp_endpoint="http://localhost:8001",  # Using our existing MCP server for testing
        mcp_api_key="test-key",
        credentials={"jira_url": "https://google.atlassian.net"}
    ),
    "microsoft": TenantConfig(
        tenant_id="microsoft",
        display_name="Microsoft",
        mcp_endpoint="http://localhost:8001",  # Same server for testing
        mcp_api_key="test-key",
        credentials={"jira_url": "https://microsoft.atlassian.net"}
    ),
    "company-c": TenantConfig(
        tenant_id="company-c",
        display_name="Company C",
        mcp_endpoint="http://localhost:8001",
        mcp_api_key="test-key",
        credentials={"jira_url": "https://companyc.atlassian.net"}
    )
}

# User-tenant mappings (will be replaced with PostgreSQL)
USER_TENANT_ACCESS: List[UserTenantAccess] = [
    # Internal employees with multi-tenant access
    UserTenantAccess("john@company.com", "google", "write"),
    UserTenantAccess("john@company.com", "microsoft", "write"),
    UserTenantAccess("admin@company.com", "google", "admin"),
    UserTenantAccess("admin@company.com", "microsoft", "admin"),
    UserTenantAccess("admin@company.com", "company-c", "admin"),
    # Client employees with single-tenant access
    UserTenantAccess("sarah@google.com", "google", "write"),
    UserTenantAccess("mike@microsoft.com", "microsoft", "write"),
    UserTenantAccess("alice@companyc.com", "company-c", "write"),
    # Test user from Phase 1
    UserTenantAccess("testuser@google.com", "google", "write"),
    UserTenantAccess("alamajacintg04@gmail.com", "google", "admin"),
    UserTenantAccess("alamajacintg04@gmail.com", "microsoft", "admin"),
    UserTenantAccess("alamajacintg04@gmail.com", "company-c", "admin"),
]

def get_user_tenants(user_email: str) -> List[TenantConfig]:
    """Get all tenants a user has access to."""
    tenant_ids = [
        access.tenant_id
        for access in USER_TENANT_ACCESS
        if access.user_email.lower() == user_email.lower()
    ]
    return [TENANTS[tid] for tid in tenant_ids if tid in TENANTS]

def get_tenant(tenant_id: str) -> Optional[TenantConfig]:
    """Get tenant config by ID."""
    return TENANTS.get(tenant_id)

def user_has_tenant_access(user_email: str, tenant_id: str) -> bool:
    """Check if user has access to a specific tenant."""
    return any(
        access.tenant_id == tenant_id and access.user_email.lower() == user_email.lower()
        for access in USER_TENANT_ACCESS
    )
```

**Step 2: Add tenant endpoints to main.py**

```python
# mcp-proxy/main.py
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from auth import extract_user_from_headers, UserInfo
from tenants import get_user_tenants, get_tenant, user_has_tenant_access

app = FastAPI(
    title="MCP Proxy Gateway",
    description="Multi-tenant MCP proxy for Open WebUI",
    version="0.1.0"
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mcp-proxy"}

@app.get("/")
async def root():
    return {"message": "MCP Proxy Gateway", "docs": "/docs"}

@app.get("/tenants")
async def list_tenants(request: Request):
    """List tenants the current user has access to."""
    user = extract_user_from_headers(request)
    tenants = get_user_tenants(user.email)
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
```

**Step 3: Test tenant access**

```bash
# Test as admin (should see all 3 tenants)
curl -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
     http://localhost:8000/tenants
# Expected: {"user": "alamajacintg04@gmail.com", "tenants": [...3 tenants...]}

# Test as Google employee (should see only Google)
curl -H "X-OpenWebUI-User-Email: sarah@google.com" \
     http://localhost:8000/tenants
# Expected: {"user": "sarah@google.com", "tenants": [{"tenant_id": "google", ...}]}

# Test as internal employee (should see Google + Microsoft)
curl -H "X-OpenWebUI-User-Email: john@company.com" \
     http://localhost:8000/tenants
# Expected: {"user": "john@company.com", "tenants": [...2 tenants...]}
```

**Step 4: Commit**

```bash
git add mcp-proxy/
git commit -m "feat(proxy): add in-memory tenant configuration and user-tenant mapping"
```

---

## Task 4: Add Tool Listing with Tenant Filtering

**Files:**
- Create: `mcp-proxy/tools.py`
- Modify: `mcp-proxy/main.py`

**Step 1: Create tools module**

```python
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
```

**Step 2: Add tools endpoint to main.py**

```python
# mcp-proxy/main.py
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from auth import extract_user_from_headers, UserInfo
from tenants import get_user_tenants, get_tenant, user_has_tenant_access
from tools import get_tools_for_user

app = FastAPI(
    title="MCP Proxy Gateway",
    description="Multi-tenant MCP proxy for Open WebUI",
    version="0.1.0"
)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mcp-proxy"}

@app.get("/")
async def root():
    return {"message": "MCP Proxy Gateway", "docs": "/docs"}

@app.get("/tenants")
async def list_tenants(request: Request):
    """List tenants the current user has access to."""
    user = extract_user_from_headers(request)
    tenants = get_user_tenants(user.email)
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
    tenants = get_user_tenants(user.email)

    if not tenants:
        return {
            "user": user.email,
            "tools": [],
            "message": "No tenant access configured for this user"
        }

    tools = await get_tools_for_user(tenants)
    return {
        "user": user.email,
        "tenant_count": len(tenants),
        "tool_count": len(tools),
        "tools": tools
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
```

**Step 3: Test tool listing**

```bash
# Test as admin (should see tools from all tenants)
curl -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
     http://localhost:8000/tools
# Expected: Multiple tools prefixed with tenant names

# Test as Google-only user
curl -H "X-OpenWebUI-User-Email: sarah@google.com" \
     http://localhost:8000/tools
# Expected: Only google_* tools
```

**Step 4: Commit**

```bash
git add mcp-proxy/
git commit -m "feat(proxy): add tool listing with tenant-based filtering"
```

---

## Task 5: Add Tool Execution with Credential Injection

**Files:**
- Modify: `mcp-proxy/tools.py`
- Modify: `mcp-proxy/main.py`

**Step 1: Add tool execution to tools.py**

```python
# mcp-proxy/tools.py - Add to existing file
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
            # These would come from Vault in production
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
```

**Step 2: Add execution endpoint to main.py**

```python
# Add to mcp-proxy/main.py
from pydantic import BaseModel
from typing import Any, Dict

class ToolExecuteRequest(BaseModel):
    arguments: Dict[str, Any] = {}

@app.post("/tools/{tenant_id}/{tool_name}")
async def execute_tool_endpoint(
    tenant_id: str,
    tool_name: str,
    request: Request,
    body: ToolExecuteRequest
):
    """Execute a tool with tenant-specific credentials."""
    from tools import execute_tool

    user = extract_user_from_headers(request)

    # Check tenant access
    if not user_has_tenant_access(user.email, tenant_id):
        raise HTTPException(
            status_code=403,
            detail=f"User {user.email} does not have access to tenant '{tenant_id}'"
        )

    tenant = get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' not found"
        )

    result = await execute_tool(tenant, tool_name, body.arguments)

    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Tool execution failed")
        )

    return result
```

**Step 3: Test tool execution**

```bash
# Test executing a tool (read_file from our MCP filesystem server)
curl -X POST \
     -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {"path": "/data/sample.txt"}}' \
     http://localhost:8000/tools/google/read_file

# Test access denied
curl -X POST \
     -H "X-OpenWebUI-User-Email: sarah@google.com" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {}}' \
     http://localhost:8000/tools/microsoft/read_file
# Expected: 403 Forbidden
```

**Step 4: Commit**

```bash
git add mcp-proxy/
git commit -m "feat(proxy): add tool execution with tenant access control and credential injection"
```

---

## Task 6: Create Docker Compose Setup

**Files:**
- Create: `mcp-proxy/Dockerfile`
- Create: `mcp-proxy/docker-compose.yml`

**Step 1: Create Dockerfile**

```dockerfile
# mcp-proxy/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Create docker-compose.yml**

```yaml
# mcp-proxy/docker-compose.yml
version: '3.8'

services:
  mcp-proxy:
    build: .
    container_name: mcp-proxy
    ports:
      - "8000:8000"
    environment:
      - DEBUG=true
    networks:
      - mcp-network
    restart: unless-stopped

networks:
  mcp-network:
    external: true
    name: io_default  # Connect to same network as Open WebUI
```

**Step 3: Build and run**

```bash
cd mcp-proxy
docker compose up -d --build
docker compose logs -f
```

**Step 4: Test containerized proxy**

```bash
curl -H "X-OpenWebUI-User-Email: alamajacintg04@gmail.com" \
     http://localhost:8000/tools
```

**Step 5: Commit**

```bash
git add mcp-proxy/
git commit -m "feat(proxy): add Docker configuration"
```

---

## Task 7: Update Open WebUI Configuration

**Files:**
- Modify: `docker-compose.yml` (root)

**Step 1: Update Open WebUI environment**

Add to the Open WebUI service in `docker-compose.yml`:

```yaml
services:
  open-webui:
    # ... existing config ...
    environment:
      - WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
      - ENABLE_FORWARD_USER_INFO_HEADERS=true  # ADD THIS LINE
```

**Step 2: Restart Open WebUI**

```bash
docker compose down
docker compose up -d
```

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(openwebui): enable user info header forwarding"
```

---

## Task 8: Add Proxy as External Tool in Open WebUI

**Steps (Manual via UI):**

1. Open http://localhost:3000
2. Login as admin (alamajacintg04@gmail.com)
3. Go to Admin Panel → Settings → External Tools
4. Click + (Add Server)
5. Enter:
   - Type: OpenAPI
   - URL: `http://host.docker.internal:8000` (or `http://mcp-proxy:8000` if same Docker network)
6. Save

**Step 2: Test integration**

1. Go to New Chat
2. Check if proxy tools appear in the integrations menu
3. Try executing a tool

**Step 3: Document completion**

```bash
git add -A
git commit -m "docs: complete Phase 2 MCP proxy gateway implementation"
```

---

## Task 9: End-to-End Testing

**Test Cases:**

### Test 1: Admin sees all tenant tools
```bash
# Login as admin in Open WebUI
# Expected: Tools from Google, Microsoft, Company C visible
```

### Test 2: Google employee sees only Google tools
```bash
# Create/login as sarah@google.com
# Expected: Only google_* tools visible
```

### Test 3: Tool execution respects permissions
```bash
# As sarah@google.com, try to call microsoft_* tool
# Expected: 403 Forbidden
```

### Test 4: Credential injection works
```bash
# Execute a tool and check logs
# Expected: Tenant credentials present in request to MCP server
```

---

## Success Criteria Checklist

- [ ] Proxy extracts user from X-OpenWebUI-User-Email header
- [ ] /tenants endpoint returns user's authorized tenants
- [ ] /tools endpoint returns filtered tools based on tenant access
- [ ] Tool execution checks tenant access before forwarding
- [ ] Credentials are injected per-tenant
- [ ] 403 returned when user lacks tenant access
- [ ] Docker setup works
- [ ] Open WebUI integration works

---

## Next Steps (Phase 3)

1. Replace in-memory storage with PostgreSQL
2. Add HashiCorp Vault for credential storage
3. Add audit logging
4. Add rate limiting
5. Create Kubernetes Helm charts
6. Add monitoring with Prometheus/Grafana
