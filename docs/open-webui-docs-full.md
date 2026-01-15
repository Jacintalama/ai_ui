# Open WebUI Documentation - Full Scrape

**Scraped Date:** January 12, 2026
**Source:** https://docs.openwebui.com/

---

## Table of Contents

1. [Overview](#overview)
2. [User Management & Admin Features](#user-management--admin-features)
3. [Authentication & SSO](#authentication--sso)
4. [Environment Variables](#environment-variables)
5. [Multi-Tenant & Enterprise Features](#multi-tenant--enterprise-features)
6. [MCP Integration](#mcp-integration)

---

## Overview

**Platform Definition:**
"An extensible, feature-rich, and user-friendly self-hosted AI platform designed to operate entirely offline" supporting Ollama and OpenAI-compatible protocols.

### Installation Methods

1. **Docker** (recommended)
   - Standard, GPU-enabled, and slim variants
   - Bundled Ollama option
   - Dev branch availability
   - Automatic/manual update tools via Watchtower

2. **Manual Installation**
   - `uv` runtime manager (recommended)
   - Python `pip` (requires Python 3.11+)
   - Postgres support available

3. **Other Options:** Docker Compose, Kustomize, Helm, experimental desktop app

**Access Point:** `http://localhost:3000` (Docker) or `http://localhost:8080` (manual)

---

## User Management & Admin Features

### Core Admin Functions

| Feature | Description |
|---------|-------------|
| **Super Admin Assignment** | First signup automatically becomes unchangeable super admin |
| **Multi-User Management** | Intuitive admin panel with pagination for streamlined user administration |
| **Admin Panel** | Offers direct user addition or **bulk CSV import** capabilities |
| **Active Users Indicator** | Monitor active users and model utilization by individual |

### User Permissions & Roles

| Feature | Description |
|---------|-------------|
| **Granular User Permissions** | Customizable role-based permissions restrict user actions |
| **Default Sign-Up Role** | Configure new signups as `pending`, `user`, or `admin` |
| **Prevent New Sign-Ups** | Disable new user registrations to maintain fixed user count |
| **Model Whitelisting** | Admins restrict model access to authorized users |

### Group Management

| Feature | Description |
|---------|-------------|
| **User Group Management** | Create and manage user groups for organization |
| **Group-Based Access Control** | Set granular access to models, knowledge, prompts, tools by group |
| **OAuth Management for User Groups** | Enhanced group-level control via OAuth integration |

### Data Import/Export

| Feature | Description |
|---------|-------------|
| **Bulk CSV Import** | Admin Panel offers bulk CSV import capabilities for users |
| **Import/Export Chat History** | Move chat data via `Import Chats` and `Export Chats` options |
| **Export All Archived Chats as JSON** | Bulk export archived conversations |
| **Download Chats as JSON/PDF/TXT** | Individual chat export in multiple formats |
| **Comprehensive Feedback Export** | Export RLHF feedback data to JSON |

---

## Authentication & SSO

### Enterprise Authentication

| Feature | Description |
|---------|-------------|
| **SCIM 2.0 Automated Provisioning** | User/group lifecycle management via Okta, Azure AD, Google Workspace |
| **LDAP Authentication** | Enhanced security with LDAP user management support |
| **Trusted Email Authentication** | Optional authentication via trusted email header |
| **Optional Authentication** | Disable authentication by setting `WEBUI_AUTH` to `False` |

### OAuth Providers Supported

- Google (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- Microsoft (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_CLIENT_TENANT_ID`)
- GitHub (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`)
- Feishu (`FEISHU_CLIENT_ID`, `FEISHU_CLIENT_SECRET`)
- Generic OIDC (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`)

### API Security

| Feature | Description |
|---------|-------------|
| **Simplified API Key Management** | Generate and manage secret keys for OpenAI library integration |
| **API Key Authentication** | Enable/disable API key authentication with configurable restrictions |
| **Advanced API Security** | Block API users via customized model filters |

---

## Environment Variables

### Authentication & Login

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `WEBUI_AUTH` | bool | True | Enables or disables authentication |
| `ENABLE_LOGIN_FORM` | bool | True | Toggles email/password signin elements |
| `ENABLE_PASSWORD_AUTH` | bool | True | Allows both password and SSO authentication methods |
| `ENABLE_SIGNUP` | bool | True | Controls user account creation |
| `WEBUI_SECRET_KEY` | str | random | Used for JWT and encryption |

### Admin Account Creation

| Variable | Type | Description |
|----------|------|-------------|
| `WEBUI_ADMIN_EMAIL` | str | Automatically creates admin on first startup |
| `WEBUI_ADMIN_PASSWORD` | str | Password for auto-created admin account |
| `WEBUI_ADMIN_NAME` | str | Display name for admin account (default: Admin) |

### User Roles & Defaults

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DEFAULT_USER_ROLE` | str | pending | Sets default role: `pending`, `user`, or `admin` |
| `DEFAULT_GROUP_ID` | str | - | Assigns default group to new users |
| `DEFAULT_MODELS` | str | - | Pre-selects default language model |

### Access Control

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BYPASS_MODEL_ACCESS_CONTROL` | bool | False | All users have access to all models |
| `BYPASS_ADMIN_ACCESS_CONTROL` | bool | True | Admins access all items regardless of permissions |
| `ENABLE_ADMIN_CHAT_ACCESS` | bool | True | Admins can access other users' chats |
| `ENABLE_API_KEYS` | bool | False | Enables API key creation feature |

### OAuth Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_OAUTH_SIGNUP` | bool | False | Enables account creation via OAuth |
| `OPENID_PROVIDER_URL` | str | - | Path to `.well-known/openid-configuration` |
| `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` | bool | False | Merges OAuth accounts with same email |
| `OAUTH_ALLOWED_DOMAINS` | str | * | Restricts access to specific email domains |

### OAuth Role & Group Management

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_OAUTH_ROLE_MANAGEMENT` | bool | False | Enables role-based access control |
| `OAUTH_ALLOWED_ROLES` | str | user,admin | Roles allowed access |
| `OAUTH_ADMIN_ROLES` | str | admin | Roles considered administrators |
| `ENABLE_OAUTH_GROUP_MANAGEMENT` | bool | False | Enables group-based access control |
| `ENABLE_OAUTH_GROUP_CREATION` | bool | False | Auto-create groups from OAuth claims |
| `OAUTH_BLOCKED_GROUPS` | str | - | JSON array of groups denied access |

### LDAP Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_LDAP` | bool | False | Enables LDAP authentication |
| `LDAP_SERVER_HOST` | str | localhost | LDAP server hostname |
| `LDAP_SERVER_PORT` | int | 389 | LDAP server port |
| `LDAP_SEARCH_BASE` | str | - | Base DN for searches |
| `LDAP_SEARCH_FILTER` | str | - | Filter appended to username filter |
| `ENABLE_LDAP_GROUP_MANAGEMENT` | bool | False | Enable LDAP group management |
| `ENABLE_LDAP_GROUP_CREATION` | bool | False | Auto-create groups from LDAP |

### SCIM Provisioning

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCIM_ENABLED` | bool | False | Enables SCIM 2.0 for automated user/group provisioning |
| `SCIM_TOKEN` | str | - | Bearer token for SCIM API authentication |

### Trusted Headers (SSO Proxy)

| Variable | Type | Description |
|----------|------|-------------|
| `WEBUI_AUTH_TRUSTED_EMAIL_HEADER` | str | Header for email authentication |
| `WEBUI_AUTH_TRUSTED_NAME_HEADER` | str | Header for username authentication |
| `WEBUI_AUTH_TRUSTED_GROUPS_HEADER` | str | Header for group memberships |

### User Permissions (Fine-Grained)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `USER_PERMISSIONS_CHAT_FILE_UPLOAD` | bool | True | Allow file uploads |
| `USER_PERMISSIONS_CHAT_DELETE` | bool | True | Allow chat deletion |
| `USER_PERMISSIONS_FEATURES_WEB_SEARCH` | bool | True | Allow web search |
| `USER_PERMISSIONS_FEATURES_IMAGE_GENERATION` | bool | True | Allow image generation |
| `USER_PERMISSIONS_FEATURES_CODE_INTERPRETER` | bool | True | Allow code interpreter |
| `USER_PERMISSIONS_FEATURES_DIRECT_TOOL_SERVERS` | bool | False | Allow direct tool server connections |

### Multi-Instance Deployment

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `REDIS_URL` | str | - | Required for multi-worker/pod deployments |
| `WEBSOCKET_MANAGER` | str | - | Set to `redis` for multi-worker |
| `DATABASE_URL` | str | sqlite | PostgreSQL for production |

---

## Multi-Tenant & Enterprise Features

### Scalability

| Feature | Description |
|---------|-------------|
| **Horizontal Scalability** | Redis-backed sessions, WebSocket support for multi-worker/node deployments |
| **Cloud Storage Backend** | Enable stateless instances with S3, Google Cloud Storage, Azure Blob Storage |
| **Multiple Ollama Load Balancing** | Distribute requests across multiple Ollama instances |

### Database Options

| Feature | Description |
|---------|-------------|
| **Flexible Database** | SQLite, Postgres, multiple vector databases |
| **Vector Databases** | ChromaDB, PostgreSQL/PGVector, Qdrant, Milvus, Elasticsearch, OpenSearch, Pinecone, S3Vector, Oracle 23ai |

### Monitoring & Compliance

| Feature | Description |
|---------|-------------|
| **Prevent Chat Deletion** | Admin toggle prevents all users from deleting messages for audit |
| **OpenTelemetry** | Export traces, metrics, logs to Prometheus, Grafana, Jaeger |
| **Webhook Integration** | Subscribe to signup events via Discord, Google Chat, Slack, Microsoft Teams |
| **Audit Logging** | `AUDIT_LOG_LEVEL`: NONE, METADATA, REQUEST, REQUEST_RESPONSE |

### Enterprise Compliance

- SOC 2, HIPAA, GDPR, FedRAMP, ISO 27001 compliance support
- On-premise and air-gapped deployment options
- 99.99% uptime availability
- White-label interface capabilities

---

## MCP Integration

### What is MCP?

"MCP is an open standard that allows LLMs to interact with external data and tools."

### Integration Approaches

| Approach | Description |
|----------|-------------|
| **Native HTTP MCP** | Direct connections to MCP servers exposing HTTP/SSE endpoints |
| **MCPO (Proxy)** | Bridge adapter for stdio-based MCP servers |

### Configuration

MCP servers are configured through `Settings > Connections`. Users can:
- Connect external tool providers without custom code
- Enable MCP tools on-the-fly during chats
- Configure tools as defaults at model level

### Tool Categories in Open WebUI

1. Native features
2. Workspace tools (Python scripts)
3. MCP connections
4. OpenAPI servers

### Security Warning

> "Never import a Tool you don't recognize or trust."
>
> Granting users permission to create or import tools "is equivalent to the ability to run arbitrary code on the server."

---

## Key Findings for Multi-Tenant User Management

### Option 1: CSV Bulk Import (Current)
- Admin Panel offers **bulk CSV import** for users
- Manual process, explicit control
- Good for initial setup

### Option 2: OAuth with Domain Filtering
```
OAUTH_ALLOWED_DOMAINS=google.com;microsoft.com
ENABLE_OAUTH_GROUP_MANAGEMENT=true
ENABLE_OAUTH_GROUP_CREATION=true
```
- Automatic user creation on OAuth login
- Domain-based access control
- Group membership from OAuth provider

### Option 3: SCIM 2.0 (Enterprise)
```
SCIM_ENABLED=true
SCIM_TOKEN=your-secret-token
```
- Automated provisioning via Okta, Azure AD, Google Workspace
- User/group lifecycle management
- Best for 15,000+ users

### Option 4: LDAP/Active Directory
```
ENABLE_LDAP=true
LDAP_SERVER_HOST=ldap.company.com
ENABLE_LDAP_GROUP_MANAGEMENT=true
```
- Integrate with existing directory
- Group-based access control

### Option 5: Trusted Header Authentication
```
WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-User-Email
WEBUI_AUTH_TRUSTED_GROUPS_HEADER=X-User-Groups
```
- API Gateway handles authentication
- Headers pass user identity to Open WebUI
- Best for reverse proxy/API Gateway setups

---

## Recommendation for Lukas (15,000 Users)

For 15,000 users across Google and Microsoft tenants:

1. **Use Microsoft Entra ID (Azure AD)** with OAuth
2. **Enable SCIM** for automated user provisioning
3. **Use OAuth Group Management** to sync groups

```yaml
# Recommended Environment Variables
ENABLE_OAUTH_SIGNUP: "true"
MICROSOFT_CLIENT_ID: "your-client-id"
MICROSOFT_CLIENT_SECRET: "your-secret"
MICROSOFT_CLIENT_TENANT_ID: "your-tenant"
ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
ENABLE_OAUTH_GROUP_CREATION: "true"
OAUTH_ALLOWED_DOMAINS: "google.com;microsoft.com"
SCIM_ENABLED: "true"
SCIM_TOKEN: "your-scim-token"
```

This way:
- Users auto-created on first OAuth login
- Groups synced from Azure AD
- MCP Proxy reads groups from `X-User-Groups` header
- No manual user management needed!
