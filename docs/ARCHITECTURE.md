# Architecture Overview

Multi-tenant AI platform with MCP tool integration.

## System Components

```
+------------------+     +------------------+     +------------------+
|   Open WebUI     |     |   MCP Proxy      |     |   MCP Servers    |
|   (Frontend)     |---->|   Gateway        |---->|   (Tools)        |
|   Port: 3000     |     |   Port: 8000     |     |   8001, 8002...  |
+------------------+     +------------------+     +------------------+
        |                        |
        v                        v
+------------------+     +------------------+
|   OpenAI API     |     |   Tenant Config  |
|   (LLM Backend)  |     |   (tenants.py)   |
+------------------+     +------------------+
```

## Two Deployment Options

| Feature | Docker Compose | Kubernetes |
|---------|---------------|------------|
| URL | localhost:3000 | localhost:8080 |
| Database | SQLite | PostgreSQL |
| Use Case | Development | Production |
| Command | `docker compose up -d` | `kubectl apply -f kubernetes/` |

## Multi-Tenant Architecture

**How it works:**
1. User logs into Open WebUI with email (e.g., `joelalama@google.com`)
2. MCP Proxy extracts user email from request headers
3. Tenant config (`tenants.py`) determines which tools the user can access
4. User only sees tools from their assigned tenants

**Tenant Mappings (tenants.py):**
- `joelalama@google.com` -> Google tenant + GitHub tenant (14 tools)
- `miketest@microsoft.com` -> Microsoft tenant only
- Admin users -> All tenants (42+ tools)

## Key Files

```
IO/
├── docker-compose.yml          # Docker development setup
├── README.md                   # Quick start & credentials
├── .env                        # Secrets (not in git)
├── mcp-proxy/                  # Multi-tenant MCP gateway
│   ├── main.py                 # FastAPI server
│   ├── tenants.py              # Tenant/user mappings
│   ├── auth.py                 # User extraction
│   └── Dockerfile              # Container build
├── mcp-servers/                # Individual MCP servers
│   └── github/                 # GitHub tools server
├── kubernetes/                 # Production deployment
│   ├── values-local.yaml       # Local K8s config
│   ├── postgresql-deployment.yaml
│   ├── mcp-proxy-deployment.yaml
│   └── mcp-*.yaml              # Other services
├── open-webui-functions/       # Custom Open WebUI tools
│   ├── mcp_proxy_bridge.py     # Docker version
│   └── mcp_proxy_bridge_k8s.py # Kubernetes version
└── docs/                       # Documentation
    ├── ARCHITECTURE.md         # This file
    ├── integration-guide.md    # Integration details
    └── plans/                  # Design documents
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| open-webui | 3000/8080 | Main UI (Chat interface) |
| mcp-proxy | 8000 | Multi-tenant tool gateway |
| mcp-filesystem | 8001 | File access tools |
| mcp-github | 8002 | GitHub API tools |
| postgresql | 5432 | Database (K8s only) |

## Adding New Tenants

1. Edit `mcp-proxy/tenants.py`
2. Add tenant configuration with MCP server URL
3. Map users to tenant in `USER_TENANT_MAPPING`
4. Restart MCP Proxy

## Adding New Users

1. Create user in Open WebUI (Admin Panel -> Users)
2. Add user email to `tenants.py` USER_TENANT_MAPPING
3. User will see tools from assigned tenants on next login

## Production Deployment

For production (Kubernetes):
1. Use PostgreSQL (row-level security with workspace_id = tenant)
2. One database, multiple workspaces
3. MCP Proxy handles tool access control

## Entra ID Integration (Enterprise)

For enterprise deployments with Microsoft Entra ID:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Browser    │────►│  API Gateway │────►│  MCP Proxy   │
│  Entra Token │     │  (Azure APIM)│     │  X-User-*    │
└──────────────┘     └──────────────┘     └──────────────┘
```

**Setup:**
1. Set `API_GATEWAY_MODE=true` on MCP Proxy
2. Configure Azure APIM with `kubernetes/api-gateway-policy.xml`
3. Create Entra ID groups: `MCP-GitHub`, `MCP-Admin`, etc.
4. See `docs/entra-id-setup.md` for full guide

**Group → Tenant Mapping:**
| Entra ID Group | Tools Access |
|----------------|--------------|
| MCP-GitHub | GitHub (51 tools) |
| MCP-Atlassian | Jira, Confluence |
| MCP-Admin | All tools |
