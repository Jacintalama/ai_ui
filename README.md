# Open WebUI Local Setup

Self-hosted AI interface running locally via Docker.

---

## ⚠️ IMPORTANT RULES FOR CLAUDE/AI ASSISTANTS ⚠️

**DO NOT COMMIT OR PUSH ANYTHING UNTIL I SAY "GO"**

1. **NO commits** to any repository without explicit approval
2. **NO pushing** to remote/origin without explicit approval
3. **NEVER touch** `C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui` - this is the **CLIENT'S REPOSITORY**
4. Only make changes to the `IO` repository (this repo)
5. When in doubt, **ASK FIRST**

**Safe repositories:**
- ✅ `C:\Users\alama\Desktop\Lukas Work\IO` - OK to edit (but ask before commit)

**OFF LIMITS:**
- ❌ `C:\Users\alama\Desktop\Lukas Work\ai_ui\ai_ui` - CLIENT REPO, DO NOT TOUCH

---

## Quick Start

```bash
docker compose up -d
```

Access: http://localhost:3000

## Credentials

### Admin Account
| Field | Value |
|-------|-------|
| **Email** | alamajacintg04@gmail.com |
| **Password** | Jacintalama123! |
| **Name** | Jacint Alama |
| **Role** | Admin |

### Test User Account (Google Tenant)
| Field | Value |
|-------|-------|
| **Email** | joelalama@google.com |
| **Password** | 123456 |
| **Name** | Joel Alama |
| **Role** | User |
| **Tenant Access** | Google, GitHub |

### Test User Account (Microsoft Tenant)
| Field | Value |
|-------|-------|
| **Email** | miketest@microsoft.com |
| **Password** | 123456 |
| **Name** | Mike Test |
| **Role** | User |
| **Tenant Access** | Microsoft only |

## OpenAI API Configuration

- **URL**: `https://api.openai.com/v1`
- **API Key**: `<YOUR_OPENAI_API_KEY>` (set in environment variables)

## Available Models

- gpt-4o, gpt-4o-mini (recommended)
- gpt-4, gpt-4-turbo
- gpt-3.5-turbo
- o1, o3, o3-mini, o4-mini
- gpt-5, gpt-5.1, gpt-5.2
- sora-2 (video generation)
- And 100+ more models

## Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `BYPASS_MODEL_ACCESS_CONTROL` | `true` | Allows all users to see all models |
| `ENABLE_FORWARD_USER_INFO_HEADERS` | `true` | Forwards user identity to MCP servers |

## Commands

```bash
# Start
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f

# Update
docker compose pull && docker compose up -d
```

## Multi-Tenant MCP Proxy Gateway

The MCP Proxy Gateway filters tools based on user's tenant access:

- **Joel** (`joelalama@google.com`) → Sees only `google_*` tools (14 tools)
- **Admin** (`alamajacintg04@gmail.com`) → Sees all tenant tools (42 tools)

See `mcp-proxy/` directory for implementation.

## Kubernetes Deployment

### Unified MCP Proxy (Lukas's Requirement)

One URL to access all MCP servers:

```
http://localhost:30800/github      → GitHub tools (40)
http://localhost:30800/filesystem  → Filesystem tools (14)
http://localhost:30800/linear      → Linear (needs API key)
http://localhost:30800/notion      → Notion (needs API key)
http://localhost:30800/sentry      → Sentry (needs API key)
http://localhost:30800/servers     → List all 11 servers
```

### Quick Start (Kubernetes)

#### Step 1: Start Docker Desktop
```
1. Open Docker Desktop
2. Wait for it to start (whale icon stops animating)
```

#### Step 2: Enable Kubernetes
```
1. Docker Desktop → Settings (gear icon)
2. Kubernetes → Check "Enable Kubernetes"
3. Click "Apply & Restart"
4. Wait for green "Kubernetes running" status
```

#### Step 3: Run Deploy Script

**Windows (PowerShell):**
```powershell
cd kubernetes
.\deploy.ps1
```

**Mac/Linux/WSL:**
```bash
cd kubernetes
chmod +x deploy.sh
./deploy.sh
```

#### Step 4: Verify Deployment
```bash
# Check all pods are running
kubectl get pods -n open-webui

# Test the MCP Proxy
curl http://localhost:30800/health
curl http://localhost:30800/servers
```

### Access URLs

| Service | URL | Description |
|---------|-----|-------------|
| **MCP Proxy** | http://localhost:30800 | Unified API for all MCP servers |
| **Open WebUI** | http://localhost:30080 | Chat interface |

### Deploy Script Options

```bash
# Full deployment (builds Docker image)
.\deploy.ps1

# Skip Docker build (faster, if image exists)
.\deploy.ps1 -SkipBuild

# Remove all resources
.\deploy.ps1 -Teardown
```

### Test Commands

```bash
# Health check
curl http://localhost:30800/health

# List all servers
curl http://localhost:30800/servers

# List GitHub tools
curl http://localhost:30800/github

# List Filesystem tools
curl http://localhost:30800/filesystem

# Execute a tool
curl -X POST http://localhost:30800/github/search_repositories \
  -H "Content-Type: application/json" \
  -d '{"query": "mcp"}'
```

### Configure API Keys (Optional)

To enable external servers (Linear, Notion, Sentry, etc.):

1. Edit `kubernetes/mcp-secrets.yaml`
2. Replace placeholder values with real API keys
3. Apply changes:
```bash
kubectl apply -f kubernetes/mcp-secrets.yaml -n open-webui
kubectl rollout restart deployment/mcp-proxy -n open-webui
```

### Troubleshooting

```bash
# Check pod status
kubectl get pods -n open-webui

# View MCP Proxy logs
kubectl logs -n open-webui deployment/mcp-proxy

# Restart MCP Proxy
kubectl rollout restart deployment/mcp-proxy -n open-webui

# Port forward if NodePort not working
kubectl port-forward svc/mcp-proxy 8080:8000 -n open-webui
```

---

### Legacy: Manual Kubernetes Deployment

```bash
# Deploy all components manually
kubectl apply -f kubernetes/

# Port forward to access
kubectl port-forward svc/open-webui 8080:8080 -n open-webui
kubectl port-forward svc/postgresql 5433:5432 -n open-webui
```

Access: http://localhost:8080

### Kubernetes PostgreSQL Database

| Field | Value |
|-------|-------|
| **Host** | `127.0.0.1` |
| **Port** | `5433` (forwarded from K8s) |
| **Database** | `openwebui` |
| **Username** | `openwebui` |
| **Password** | `localdevpassword` |
| **Connection URL** | `postgresql://openwebui:localdevpassword@postgresql:5432/openwebui` |

### pgAdmin (Database GUI)

| Field | Value |
|-------|-------|
| **URL** | http://localhost:5050 |
| **Email** | admin@openwebui.local |
| **Password** | admin123 |

**To connect to PostgreSQL from pgAdmin:**
| Setting | Value |
|---------|-------|
| **Host** | `host.docker.internal` (Docker) or `127.0.0.1` |
| **Port** | `5433` (forwarded) or `5432` (internal) |
| **Database** | `openwebui` |
| **Username** | `openwebui` |
| **Password** | `localdevpassword` |

**Start pgAdmin (Docker):**
```bash
docker run -d -p 5050:80 \
  -e PGADMIN_DEFAULT_EMAIL=admin@openwebui.local \
  -e PGADMIN_DEFAULT_PASSWORD=admin123 \
  --name pgadmin \
  dpage/pgadmin4
```

### Kubernetes Pods

| Pod | Port | Purpose |
|-----|------|---------|
| open-webui | 8080 | Main application |
| postgresql | 5432 | Database (27 tables) |
| mcp-proxy | 8000 | Multi-tenant MCP gateway |
| mcp-filesystem | 8001 | Filesystem tools |
| mcp-github | 8002 | GitHub tools |
| open-webui-redis | 6379 | Session cache |
| open-webui-pipelines | 9099 | AI pipelines |
| open-webui-ollama | 11434 | Ollama LLM server |
| llama-cpp | 8080 | Llama.cpp server (CPU) |

### Kubernetes Test Accounts

| User | Email | Password | Role | Tenant Access |
|------|-------|----------|------|---------------|
| **Jacint (Admin)** | alamajacintg04@gmail.com | 123456 | Admin | ALL servers |
| **Joel (Google)** | joelalama@google.com | 123456 | User | Google, GitHub |
| **Mike (Microsoft)** | miketest@microsoft.com | 123456 | User | Microsoft only |

**Multi-Tenant Test:**
- Joel can access: `/github` ✅, `/filesystem` ❌
- Mike can access: `/github` ❌, `/filesystem` ❌
- Admin can access: ALL servers ✅

### Kubernetes Ollama (Local LLMs)

| Setting | Value |
|---------|-------|
| **Status** | Enabled |
| **Model** | llama3.2:latest (3.2B, 2GB) |
| **Service** | open-webui-ollama.open-webui.svc.cluster.local:11434 |

To pull additional models:
```bash
kubectl exec -it $(kubectl get pods -n open-webui -l app.kubernetes.io/name=ollama -o jsonpath='{.items[0].metadata.name}') -n open-webui -- ollama pull <model-name>
```

### Kubernetes Llama.cpp (Lightweight Local LLMs)

| Setting | Value |
|---------|-------|
| **Status** | Enabled |
| **Model** | Qwen2.5-0.5B-Instruct (Q4_K_M, 469MB) |
| **Service** | llama-cpp.open-webui.svc.cluster.local:8080 |
| **API** | OpenAI-compatible |

Deploy llama.cpp:
```bash
kubectl apply -f kubernetes/llama-cpp-deployment.yaml
```

### Kubernetes vLLM (High-Throughput GPU Inference)

| Setting | Value |
|---------|-------|
| **Status** | Requires NVIDIA GPU |
| **Model** | Qwen2.5-0.5B-Instruct (configurable) |
| **Service** | vllm.open-webui.svc.cluster.local:8000 |
| **API** | OpenAI-compatible |

Deploy vLLM (GPU required):
```bash
kubectl apply -f kubernetes/vllm-deployment.yaml
```

### Local LLM Engines Comparison

| Engine | GPU Required | Best For |
|--------|-------------|----------|
| **Ollama** | Optional | Easy setup, model management |
| **Llama.cpp** | No (CPU OK) | Lightweight, low memory |
| **vLLM** | Yes (NVIDIA) | High throughput, production |

### Two Environments

| Environment | URL | Database |
|-------------|-----|----------|
| Docker Compose | localhost:3000 | SQLite |
| Kubernetes | localhost:8080 | PostgreSQL |

## Files

```
├── docker-compose.yml    # Docker Compose configuration
├── .env                  # Secret key (DO NOT COMMIT)
├── .gitignore            # Ignores .env
├── README.md             # This file
│
├── mcp-proxy/            # Unified MCP Proxy Gateway
│   ├── main.py           # FastAPI server with /{server}/{tool} routing
│   ├── tenants.py        # Server configs (11 servers, 3 tiers)
│   ├── auth.py           # User extraction from headers
│   ├── Dockerfile        # Docker build file
│   └── requirements.txt  # Python dependencies
│
├── kubernetes/           # Kubernetes deployment files
│   ├── deploy.ps1        # Windows deployment script
│   ├── deploy.sh         # Mac/Linux deployment script
│   ├── namespace.yaml    # open-webui namespace
│   ├── mcp-secrets.yaml  # API keys (edit before deploy)
│   ├── mcp-proxy-deployment.yaml      # Unified MCP Proxy (port 30800)
│   ├── mcp-filesystem-deployment.yaml # Filesystem MCP server
│   ├── mcp-github-deployment.yaml     # GitHub MCP server
│   ├── mcpo-sse-deployment.yaml       # Tier 2: SSE servers
│   ├── mcpo-stdio-deployment.yaml     # Tier 3: stdio servers
│   ├── postgresql-deployment.yaml     # PostgreSQL database
│   ├── llama-cpp-deployment.yaml      # Llama.cpp server (CPU)
│   └── values-local.yaml              # Helm values for local testing
│
└── docs/
    ├── plans/                         # Design documents
    │   └── 2026-01-09-unified-mcp-proxy-implementation.md
    └── *.png                          # Screenshots
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Open WebUI (localhost:30080)                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              Unified MCP Proxy (localhost:30800)                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  /github ────► mcp-github (local, 40 tools)             │    │
│  │  /filesystem ► mcp-filesystem (local, 14 tools)         │    │
│  │  /linear ────► https://mcp.linear.app (external)        │    │
│  │  /notion ────► https://mcp.notion.com (external)        │    │
│  │  /sentry ────► https://mcp.sentry.dev (external)        │    │
│  │  /atlassian ─► mcpo-sse proxy (Tier 2)                  │    │
│  │  /sonarqube ─► mcpo-stdio proxy (Tier 3)                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Multi-Tenant MCP Authentication (Entra ID)

This feature enables **group-based access control** for MCP servers using Microsoft Entra ID (Azure AD) authentication.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION FLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. User logs in via Microsoft Entra ID (OAuth)                             │
│                         │                                                    │
│                         ▼                                                    │
│  2. Open WebUI receives OAuth token with user info & groups                 │
│                         │                                                    │
│                         ▼                                                    │
│  3. User sends chat message with MCP tool request                           │
│                         │                                                    │
│                         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  MCP Entra Token Auth Function (open-webui-functions/)              │    │
│  │  ─────────────────────────────────────────────────────              │    │
│  │  • Receives __oauth_token__ from Open WebUI                         │    │
│  │  • Decodes JWT to extract: email, name, groups                      │    │
│  │  • Sends request to MCP Proxy with headers:                         │    │
│  │    - X-Auth-Source: entra-token                                     │    │
│  │    - X-OpenWebUI-User-Email: user@company.com                       │    │
│  │    - X-Entra-Groups: MCP-GitHub,MCP-Admin                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                         │                                                    │
│                         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  MCP Proxy (mcp-proxy/)                                             │    │
│  │  ─────────────────────                                              │    │
│  │  • auth.py: Validates headers, extracts user info                   │    │
│  │  • db.py: Queries PostgreSQL for access permissions                 │    │
│  │  • tenants.py: Filters servers based on user's groups               │    │
│  │  • Returns ONLY authorized MCP servers/tools                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                         │                                                    │
│                         ▼                                                    │
│  4. User sees only their authorized tools (e.g., GitHub, Filesystem)        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **MCP Entra Token Auth** | `open-webui-functions/mcp_entra_token_auth.py` | Open WebUI function that reads `__oauth_token__` and forwards user info to MCP Proxy |
| **Auth Module** | `mcp-proxy/auth.py` | Validates JWT tokens, extracts user info from headers |
| **Database Module** | `mcp-proxy/db.py` | PostgreSQL queries for `user_tenant_access` and `group_tenant_mapping` tables |
| **Tenants Module** | `mcp-proxy/tenants.py` | Server definitions and access control logic |

### Database Tables

```sql
-- User-based access (direct assignment)
CREATE TABLE user_tenant_access (
    user_email VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    access_level VARCHAR(50) DEFAULT 'read',
    PRIMARY KEY (user_email, tenant_id)
);

-- Group-based access (Entra ID groups)
CREATE TABLE group_tenant_mapping (
    group_name VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    PRIMARY KEY (group_name, tenant_id)
);

-- Example data
INSERT INTO group_tenant_mapping (group_name, tenant_id) VALUES
    ('MCP-GitHub', 'github'),
    ('MCP-Filesystem', 'filesystem'),
    ('MCP-Admin', 'github'),
    ('MCP-Admin', 'filesystem'),
    ('MCP-Admin', 'atlassian');

INSERT INTO user_tenant_access (user_email, tenant_id, access_level) VALUES
    ('kimcalicoy24@gmail.com', 'github', 'read'),
    ('kimcalicoy24@gmail.com', 'filesystem', 'read');
```

### Access Control Priority

1. **MCP-Admin Group**: Users in this group have access to ALL MCP servers
2. **Group-based Access**: Check `group_tenant_mapping` table for user's Entra ID groups
3. **User-based Access**: Check `user_tenant_access` table for direct email assignment

### Setup Instructions

#### 1. Configure Entra ID Groups (Azure Portal)

1. Go to Azure Portal → Microsoft Entra ID → Groups
2. Create groups:
   - `MCP-GitHub` - Access to GitHub MCP server
   - `MCP-Filesystem` - Access to Filesystem MCP server
   - `MCP-Admin` - Access to ALL MCP servers
3. Assign users to appropriate groups

#### 2. Configure Token Claims

1. Azure Portal → App Registrations → Your App → Token Configuration
2. Add optional claim: `groups`
3. If >200 groups, configure "groups overage" to use Graph API

#### 3. Create Database Tables

```bash
# Connect to PostgreSQL
kubectl exec -it postgresql-0 -n open-webui -- psql -U openwebui -d openwebui

# Run the CREATE TABLE statements above
```

#### 4. Enable the Function in Open WebUI

1. Login as Admin
2. Go to Workspace → Functions
3. Find "MCP Entra Token Auth"
4. Click Access → Change to "Public"
5. Save

### Testing

```bash
# Check user's authorized servers
curl -H "Authorization: Bearer <token>" \
     -H "X-OpenWebUI-User-Email: user@company.com" \
     -H "X-Entra-Groups: MCP-GitHub" \
     http://localhost:30800/servers

# Expected: Only servers the user has access to
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://openwebui:password@postgresql:5432/openwebui` |
| `WEBUI_SECRET_KEY` | JWT signing key (must match Open WebUI) | `your-secret-key` |
| `API_GATEWAY_MODE` | Trust external gateway headers | `false` |
| `DEBUG` | Enable debug logging | `true` |

### Troubleshooting

```bash
# Check MCP Proxy logs for auth issues
kubectl logs -n open-webui deployment/mcp-proxy | grep -E "\[AUTH\]|\[DB\]|\[TENANTS\]"

# Verify database connection
kubectl exec -it postgresql-0 -n open-webui -- psql -U openwebui -d openwebui -c "SELECT * FROM group_tenant_mapping;"

# Test with specific user
curl -H "X-Auth-Source: entra-token" \
     -H "X-OpenWebUI-User-Email: test@company.com" \
     -H "X-Entra-Groups: MCP-GitHub" \
     http://localhost:30800/servers
```
