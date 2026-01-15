# Lukas AI UI Repository Analysis

**Repository:** https://github.com/TheLukasHenry/ai_ui
**Type:** Fork of open-webui/open-webui
**Date Analyzed:** January 12, 2026

---

## Overview

This is a **standard fork** of the Open WebUI project. No custom Kubernetes or MCP configurations found - it uses the default Open WebUI setup.

---

## Repository Structure

### Docker Compose Files
| File | Purpose |
|------|---------|
| `docker-compose.yaml` | Primary (Ollama + Open WebUI) |
| `docker-compose.gpu.yaml` | NVIDIA GPU support |
| `docker-compose.amdgpu.yaml` | AMD GPU support |
| `docker-compose.api.yaml` | API-only mode |
| `docker-compose.data.yaml` | Data volume config |
| `docker-compose.otel.yaml` | OpenTelemetry |

### Main Directories
| Directory | Contents |
|-----------|----------|
| `backend/` | Python FastAPI server |
| `src/` | Svelte frontend |
| `static/` | Static assets |
| `scripts/` | Build scripts |
| `docs/` | Documentation |

---

## Default Docker Compose Configuration

```yaml
services:
  ollama:
    image: ollama/ollama:${OLLAMA_DOCKER_TAG-latest}
    container_name: ollama
    volumes:
      - ollama:/root/.ollama
    restart: unless-stopped

  open-webui:
    image: ghcr.io/open-webui/open-webui:${WEBUI_DOCKER_TAG-main}
    container_name: open-webui
    volumes:
      - open-webui:/app/backend/data
    ports:
      - "${OPEN_WEBUI_PORT-3000}:8080"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - WEBUI_SECRET_KEY=
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama:
  open-webui:
```

---

## Default .env.example

```bash
OLLAMA_BASE_URL='http://localhost:11434'
OPENAI_API_BASE_URL=''
OPENAI_API_KEY=''
CORS_ALLOW_ORIGIN='*'
FORWARDED_ALLOW_IPS='*'
SCARF_NO_ANALYTICS='true'
DO_NOT_TRACK='true'
ANONYMIZED_TELEMETRY='false'
```

---

## OAuth Configuration (From Backend Config)

### Microsoft Entra ID / Azure AD
```yaml
MICROSOFT_CLIENT_ID: ""
MICROSOFT_CLIENT_SECRET: ""
MICROSOFT_CLIENT_TENANT_ID: ""
```

### Google OAuth
```yaml
GOOGLE_CLIENT_ID: ""
GOOGLE_CLIENT_SECRET: ""
```

### GitHub OAuth
```yaml
GITHUB_CLIENT_ID: ""
GITHUB_CLIENT_SECRET: ""
```

### Generic OIDC
```yaml
OAUTH_CLIENT_ID: ""
OAUTH_CLIENT_SECRET: ""
OPENID_PROVIDER_URL: ""
```

### OAuth Feature Flags
```yaml
ENABLE_OAUTH_SIGNUP: "true"           # Allow OAuth user registration
OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "true" # Merge existing accounts
ENABLE_OAUTH_ROLE_MANAGEMENT: "true"  # Map OAuth roles
ENABLE_OAUTH_GROUP_MANAGEMENT: "true" # Sync groups from OAuth
ENABLE_OAUTH_GROUP_CREATION: "true"   # Auto-create groups
OAUTH_ALLOWED_DOMAINS: "*"            # Or "google.com;microsoft.com"
```

### OAuth Claims Mapping
```yaml
OAUTH_USERNAME_CLAIM: "name"
OAUTH_EMAIL_CLAIM: "email"
OAUTH_PICTURE_CLAIM: "picture"
OAUTH_GROUPS_CLAIM: "groups"
OAUTH_ROLES_CLAIM: "roles"
```

---

## LDAP Configuration (From Backend Config)

```yaml
ENABLE_LDAP: "true"
LDAP_SERVER_HOST: "ldap.company.com"
LDAP_SERVER_PORT: "389"
LDAP_USE_TLS: "true"
LDAP_APP_DN: "cn=service,dc=company,dc=com"
LDAP_APP_PASSWORD: "secret"
LDAP_SEARCH_BASE: "ou=users,dc=company,dc=com"
LDAP_ATTRIBUTE_FOR_USERNAME: "uid"
LDAP_ATTRIBUTE_FOR_MAIL: "mail"
ENABLE_LDAP_GROUP_MANAGEMENT: "true"
ENABLE_LDAP_GROUP_CREATION: "true"
LDAP_ATTRIBUTE_FOR_GROUPS: "memberOf"
```

---

## User Permissions System

The backend has a comprehensive permissions system:

### Workspace Permissions
- `WORKSPACE_MODELS_ACCESS` - Access to models
- `WORKSPACE_KNOWLEDGE_ACCESS` - Access to knowledge base
- `WORKSPACE_PROMPTS_ACCESS` - Access to prompts
- `WORKSPACE_TOOLS_ACCESS` - Access to tools

### Chat Permissions
- `CHAT_FILE_UPLOAD` - Upload files in chat
- `CHAT_DELETE` - Delete chats
- `CHAT_EDIT` - Edit messages
- `CHAT_TEMPORARY` - Temporary chats

### Feature Permissions
- `FEATURES_WEB_SEARCH` - Web search
- `FEATURES_IMAGE_GENERATION` - Image generation
- `FEATURES_CODE_INTERPRETER` - Code execution

### Admin Controls
- `BYPASS_ADMIN_ACCESS_CONTROL` - Admins bypass restrictions
- `ENABLE_ADMIN_CHAT_ACCESS` - Admins can view user chats

---

## What Lukas Needs to Add for Multi-Tenant MCP

Since this is a standard Open WebUI fork, to add multi-tenant MCP support:

### Option 1: Add Environment Variables to Deployment

```yaml
# Add to docker-compose.yaml or deployment config
environment:
  # Microsoft Entra ID
  - MICROSOFT_CLIENT_ID=your-client-id
  - MICROSOFT_CLIENT_SECRET=your-secret
  - MICROSOFT_CLIENT_TENANT_ID=your-tenant

  # OAuth settings
  - ENABLE_OAUTH_SIGNUP=true
  - ENABLE_OAUTH_GROUP_MANAGEMENT=true
  - ENABLE_OAUTH_GROUP_CREATION=true
  - OAUTH_ALLOWED_DOMAINS=google.com;microsoft.com

  # User info forwarding (for MCP Proxy)
  - ENABLE_FORWARD_USER_INFO_HEADERS=true
  - BYPASS_MODEL_ACCESS_CONTROL=true
```

### Option 2: Create Custom docker-compose.mcp.yaml

I can create a new docker-compose file that includes:
1. Open WebUI with OAuth configured
2. MCP Proxy Gateway
3. MCP Servers (GitHub, Filesystem, etc.)

---

## Recommendations for Lukas

1. **Keep the fork updated** with upstream Open WebUI (currently on v0.6.43, v0.7.2 available)

2. **Add OAuth configuration** via environment variables - no code changes needed

3. **Integrate MCP Proxy** as a separate service or sidecar

4. **Use Groups feature** for tool access control - already supported in Open WebUI

---

## Files to Potentially Modify

| File | Change |
|------|--------|
| `docker-compose.yaml` | Add OAuth env vars, add MCP services |
| `.env.example` | Add OAuth and MCP configuration examples |
| New: `docker-compose.mcp.yaml` | Complete MCP integration setup |
| New: `mcp-proxy/` | MCP Proxy Gateway (copy from our project) |
