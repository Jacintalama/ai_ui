# Phase 2 Analysis & Validation

## Client Description Analysis

### What the Client Said (Verbatim Key Points)

| Client Statement | Our Understanding | Status |
|-----------------|-------------------|--------|
| "Company GPT for 15,000 employees" | Open WebUI deployment at enterprise scale | ✅ Correct |
| "Different clients: Google, Microsoft, small company" | Multi-tenant architecture with tenant isolation | ✅ Correct |
| "Each client needs separated data" | Per-tenant data isolation required | ✅ Correct |
| "Microsoft clients don't see Google's data" | Strict tenant boundary enforcement | ✅ Correct |
| "Integrating Jira or Atlassian with API key" | MCP tools with per-tenant credentials | ✅ Correct |
| "Google employees only access Google Jira" | User-tenant permission mapping | ✅ Correct |
| "Internal employee working for both MS and Google" | Cross-tenant access for internal staff | ✅ Correct |
| "Access and permission handling, authentication" | The core challenge identified | ✅ Correct |
| "API gateway and registry of our own server" | Custom proxy gateway solution | ✅ Matches our recommendation |
| "Already deployed with Kubernetes" | Production-ready infrastructure exists | ✅ Noted |
| "How to add MCP server Claude" | Need Claude/Anthropic integration | 🔍 Researched below |

### Validation: Is Our Phase 1 Work Accurate?

**YES - Our Phase 1 work directly addresses the client's requirements:**

1. **✅ We proved MCP tools are global** - This confirms the client's concern about "cannot do it for all different clients"

2. **✅ We designed a proxy gateway** - This matches the client's mention of "API gateway and registry of our own server"

3. **✅ We modeled user-tenant mapping** - Our `UserTenantAccess` model handles "internal employee working for both MS and Google"

4. **✅ We planned for per-tenant credentials** - Our `TenantConfig.credentials` handles "API key for each client's Jira"

---

## Claude/Anthropic MCP Integration Research

### Option 1: Anthropic MCP Connection Pipe (Recommended)

**Source:** [Anthropic MCP Connection Pipe](https://openwebui.com/f/velvoelmhelmes/anthropic_mcp_connection_pipe)

A community Function that connects Claude models with MCP servers.

**Setup:**
```bash
# In OpenWebUI container/venv
pip install mcp pydantic>=2.0.0 aiohttp>=3.8.0

# Environment variables needed
ANTHROPIC_API_KEY=sk-ant-xxx
MCP_SERVER_COMMAND=uvx
MCP_SERVER_ARGS=mcpo --port 8001
```

**Capabilities:**
- Supports Claude 3.5 Sonnet, Haiku, Opus
- Detects and executes tool calls from Claude responses
- Handles filesystem, git, database operations
- Auto-chunks large files (>8000 chars)

### Option 2: Basic Anthropic Function

**Source:** [Anthropic Function](https://openwebui.com/f/justinrahb/anthropic)

Simpler integration - just adds Claude models without MCP tool support.

**Setup:**
1. Go to Workspace → Functions
2. Import from community
3. Add ANTHROPIC_API_KEY

### Option 3: Anthropic Claude Model Access Function

**Source:** [Claude Model Access](https://openwebui.com/f/captresolve/anthropic_claude_model_access)

Production-ready integration with:
- Dynamic model discovery
- Intelligent caching
- Extended thinking support
- Full tool support

### Recommendation for Multi-Tenant

For the client's use case, **Option 1 (Anthropic MCP Connection Pipe)** is best because:
- It supports MCP tools (needed for Jira/Atlassian)
- Works with our proxy gateway architecture
- Claude can call tools through the same proxy as other models

---

## Phase 2 Tasks

### Task 1: Create FastAPI Proxy Skeleton

**Goal:** Build the basic proxy server structure

**Files:**
- `mcp-proxy/main.py` - FastAPI application
- `mcp-proxy/requirements.txt` - Dependencies
- `mcp-proxy/Dockerfile` - Container image

**Key Endpoints:**
```python
GET  /tools              # List tools for current user
POST /tools/{tenant}/{tool}/execute  # Execute with credentials
GET  /tenants            # List user's tenants
GET  /health             # Health check
```

### Task 2: Implement User-Tenant Mapping

**Goal:** Map users to their authorized tenants

**Approach:**
- Extract user from JWT (email claim)
- Query database for user's tenant memberships
- Return filtered tool list

**Test Cases:**
- User in Google-Tenant only → sees only Google tools
- User in both → sees both tenant tools
- User in none → sees no tools

### Task 3: Implement Credential Injection

**Goal:** Inject per-tenant API keys into MCP requests

**Approach:**
- Store credentials in Vault (or encrypted DB for PoC)
- Resolve credentials at request time
- Never log credentials

### Task 4: Integrate with Open WebUI

**Goal:** Add proxy as External Tool in Open WebUI

**Steps:**
1. Deploy proxy to accessible endpoint
2. Add to Admin → Settings → External Tools
3. Test tool execution flow

### Task 5: Add Claude/Anthropic Support

**Goal:** Enable Claude models with MCP tools

**Steps:**
1. Install Anthropic MCP Connection Pipe function
2. Configure ANTHROPIC_API_KEY
3. Test Claude calling tools through proxy

---

## Architecture Diagram (Updated)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           OPEN WEBUI                                     │
│                     (15,000 employees)                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      │
│  │   OpenAI    │  │  Anthropic  │  │   Ollama    │  ← LLM Providers     │
│  │   Models    │  │   Claude    │  │   Local     │                      │
│  └─────────────┘  └─────────────┘  └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      MCP PROXY GATEWAY                                   │
│                     (FastAPI + Vault)                                    │
│                                                                          │
│  1. Authenticate user (JWT)                                              │
│  2. Look up user's tenants                                               │
│  3. Filter tools by tenant access                                        │
│  4. Inject tenant credentials                                            │
│  5. Forward to correct MCP backend                                       │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Google Tenant   │  │ Microsoft       │  │ Company C       │
│ MCP Server      │  │ Tenant MCP      │  │ Tenant MCP      │
│                 │  │ Server          │  │ Server          │
│ - Google Jira   │  │ - MS Jira       │  │ - C's Jira      │
│ - Google APIs   │  │ - MS APIs       │  │ - C's APIs      │
│ (API Key: G1)   │  │ (API Key: M1)   │  │ (API Key: C1)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Open Questions for Client

1. **SSO Provider:** What SSO system is used? (Azure AD, Okta, Keycloak?)
   - This affects how we sync user-tenant mappings

2. **Credential Storage:** Is HashiCorp Vault available, or use encrypted DB?
   - Affects security architecture

3. **Anthropic API Key:** Does client have Anthropic API access for Claude?
   - Needed for Claude integration

4. **First Tenant to Test:** Which client (Google/MS/other) should we pilot first?
   - Helps prioritize MCP server setup

---

## Sources

- [Anthropic MCP Connection Pipe](https://openwebui.com/f/velvoelmhelmes/anthropic_mcp_connection_pipe)
- [Anthropic Function](https://openwebui.com/f/justinrahb/anthropic)
- [Claude Model Access Function](https://openwebui.com/f/captresolve/anthropic_claude_model_access)
- [Open WebUI Anthropic Discussion](https://github.com/open-webui/open-webui/discussions/1253)
- [MCP Guide - The Register](https://www.theregister.com/2025/04/21/mcp_guide/)
