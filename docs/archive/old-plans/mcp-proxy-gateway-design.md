# MCP Proxy Gateway Design Document

**Version:** 1.0
**Date:** 2026-01-06
**Status:** Draft

---

## 1. Overview

### Purpose

The MCP Proxy Gateway is a multi-tenant middleware service that sits between Open WebUI and tenant-specific MCP (Model Context Protocol) servers. It provides:

1. **User-Tenant Access Control** - Filters available tools based on user's tenant memberships
2. **Credential Injection** - Injects tenant-specific API credentials into MCP requests
3. **Audit Logging** - Tracks all tool executions for compliance
4. **Centralized Management** - Single point of control for all tenant MCP configurations

### Problem Statement

Open WebUI's MCP integration exposes all configured tools globally to all users. For a 15,000-employee company serving multiple clients (Google, Microsoft, etc.), we need:

- Client employees only see their company's tools
- Internal employees may access multiple clients' tools
- Each client's API credentials remain isolated
- Complete audit trail for compliance

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Open WebUI                                      │
│                          (Single Instance)                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP + JWT
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP Proxy Gateway                                   │
│                         (FastAPI Service)                                    │
│                                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ JWT Authz   │  │ Tenant       │  │ Credential  │  │ Audit Logger     │  │
│  │ Middleware  │  │ Router       │  │ Injector    │  │                  │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                  │                  │                  │
          ▼                  ▼                  ▼                  ▼
   ┌───────────┐      ┌───────────┐      ┌───────────┐      ┌───────────┐
   │ Postgres  │      │ HashiCorp │      │ MCP       │      │ MCP       │
   │ Database  │      │ Vault     │      │ Google    │      │ Microsoft │
   └───────────┘      └───────────┘      └───────────┘      └───────────┘
```

---

## 2. Data Models

### 2.1 UserTenantAccess

Maps users to their authorized tenants with access levels.

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

@dataclass
class UserTenantAccess:
    """
    Represents a user's access to a specific tenant.

    A user can have access to multiple tenants (e.g., internal employees
    working across multiple clients), while client employees typically
    have access to only their own tenant.
    """

    id: int                    # Primary key (auto-generated)
    user_id: str               # User identifier from SSO/OAuth
                               # Format: email address or UUID
                               # Example: "john.doe@company.com" or "user_abc123"

    tenant_id: str             # Tenant identifier (slug format)
                               # Must match TenantConfig.tenant_id
                               # Example: "google", "microsoft", "company-c"

    access_level: Literal["read", "write", "admin"]
                               # read: Can view tools and read data
                               # write: Can execute tools that modify data
                               # admin: Can manage tenant configuration

    granted_by: str            # User ID who granted this access
                               # Used for audit trail
                               # Example: "admin@company.com"

    granted_at: datetime       # Timestamp when access was granted
                               # UTC timezone

    expires_at: datetime | None  # Optional expiration for temporary access
                                 # None = permanent access

    source: Literal["manual", "sso_group", "hr_system"]
                               # How this access was assigned
                               # manual: Admin manually assigned
                               # sso_group: Synced from SSO group membership
                               # hr_system: Imported from HR system
```

### 2.2 TenantConfig

Configuration for each tenant including their MCP endpoint and credentials.

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class TenantConfig:
    """
    Configuration for a tenant's MCP integration.

    Each tenant represents a client organization (Google, Microsoft, etc.)
    with their own isolated MCP server instance and API credentials.
    """

    tenant_id: str             # Unique identifier (URL-safe slug)
                               # Used in API paths: /tools/{tenant_id}/...
                               # Example: "google", "microsoft", "company-c"
                               # Constraints: lowercase, alphanumeric + hyphens

    display_name: str          # Human-readable name for UI display
                               # Example: "Google", "Microsoft", "Company C"

    description: str           # Optional description of the tenant
                               # Example: "Google Cloud Platform integration"

    mcp_endpoint: str          # Base URL of tenant's MCP server (mcpo instance)
                               # Example: "http://mcp-google:8001"
                               # For Kubernetes: "http://mcp-google.mcp-namespace.svc:8001"

    mcp_api_key: str           # API key for authenticating to mcpo
                               # This is the mcpo --api-key value
                               # IMPORTANT: Store reference to Vault secret, not raw value
                               # Example: "vault:secret/mcp/google/api-key"

    credentials: dict[str, Any]  # Encrypted tenant-specific API credentials
                                 # These are injected into MCP tool calls
                                 # Example:
                                 # {
                                 #   "jira_api_token": "vault:secret/mcp/google/jira",
                                 #   "confluence_api_token": "vault:secret/mcp/google/confluence",
                                 #   "jira_base_url": "https://google.atlassian.net"
                                 # }

    enabled: bool              # Whether this tenant is active
                               # Disabled tenants won't appear in tool lists

    created_at: datetime       # Timestamp when tenant was created

    updated_at: datetime       # Timestamp when tenant was last modified

    metadata: dict[str, Any]   # Additional tenant metadata
                               # Example: {"region": "us-west-2", "tier": "enterprise"}
```

### 2.3 TenantTools

Defines which tools are available for each tenant.

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class TenantTools:
    """
    Maps tools to tenants with per-tenant configuration.

    This allows fine-grained control over which tools are available
    for each tenant, even if the underlying MCP server exposes more tools.
    """

    id: int                    # Primary key (auto-generated)

    tenant_id: str             # Foreign key to TenantConfig.tenant_id
                               # Example: "google"

    tool_name: str             # Tool identifier as exposed by MCP server
                               # Example: "jira_create_issue", "confluence_search"

    display_name: str          # Human-readable name for UI
                               # Example: "Create Jira Issue"

    description: str           # Tool description shown in UI
                               # Example: "Creates a new issue in Jira"

    enabled: bool              # Whether this tool is active for the tenant
                               # Allows disabling tools without removing config

    required_access_level: Literal["read", "write", "admin"]
                               # Minimum access level required to use this tool
                               # read: Read-only tools (search, list)
                               # write: Tools that modify data (create, update)
                               # admin: Administrative tools

    rate_limit: int | None     # Optional rate limit (requests per minute)
                               # None = no rate limit
                               # Example: 60 (1 request per second)

    credential_keys: list[str]  # Which credentials from TenantConfig.credentials
                                # are needed for this tool
                                # Example: ["jira_api_token", "jira_base_url"]

    tool_config: dict[str, Any]  # Additional tool-specific configuration
                                  # Example: {"default_project": "PROJ-123"}

    created_at: datetime       # Timestamp when tool was added

    updated_at: datetime       # Timestamp when tool config was modified
```

---

## 3. Database Schema

PostgreSQL schema for the data models.

```sql
-- ============================================================================
-- MCP Proxy Gateway Database Schema
-- PostgreSQL 15+
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- Tenant Configuration Table
-- ============================================================================

CREATE TABLE tenant_configs (
    tenant_id VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',

    -- MCP Server Connection
    mcp_endpoint VARCHAR(512) NOT NULL,
    mcp_api_key_ref VARCHAR(512) NOT NULL,  -- Vault reference, not raw key

    -- Encrypted credentials stored as JSONB
    -- Values are Vault references: {"jira_token": "vault:secret/..."}
    credentials JSONB DEFAULT '{}',

    -- Status
    enabled BOOLEAN DEFAULT TRUE,

    -- Metadata
    metadata JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT tenant_id_format CHECK (tenant_id ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$'),
    CONSTRAINT mcp_endpoint_format CHECK (mcp_endpoint ~ '^https?://'),
    CONSTRAINT display_name_not_empty CHECK (LENGTH(TRIM(display_name)) > 0)
);

-- Index for listing enabled tenants
CREATE INDEX idx_tenant_configs_enabled ON tenant_configs(enabled) WHERE enabled = TRUE;

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tenant_configs_updated_at
    BEFORE UPDATE ON tenant_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- User-Tenant Access Table
-- ============================================================================

CREATE TABLE user_tenant_access (
    id SERIAL PRIMARY KEY,

    -- User identification (from SSO/OAuth)
    user_id VARCHAR(255) NOT NULL,

    -- Tenant reference
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenant_configs(tenant_id) ON DELETE CASCADE,

    -- Access control
    access_level VARCHAR(16) NOT NULL CHECK (access_level IN ('read', 'write', 'admin')),

    -- Audit trail
    granted_by VARCHAR(255) NOT NULL,
    granted_at TIMESTAMPTZ DEFAULT NOW(),

    -- Optional expiration for temporary access
    expires_at TIMESTAMPTZ DEFAULT NULL,

    -- Source of access grant
    source VARCHAR(32) NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'sso_group', 'hr_system')),

    -- Unique constraint: user can only have one access entry per tenant
    UNIQUE(user_id, tenant_id)
);

-- Index for looking up user's tenants (most common query)
CREATE INDEX idx_user_tenant_access_user_id ON user_tenant_access(user_id);

-- Index for finding all users of a tenant
CREATE INDEX idx_user_tenant_access_tenant_id ON user_tenant_access(tenant_id);

-- Index for finding expired access (for cleanup jobs)
CREATE INDEX idx_user_tenant_access_expires
    ON user_tenant_access(expires_at)
    WHERE expires_at IS NOT NULL;

-- Partial index for active (non-expired) access
CREATE INDEX idx_user_tenant_access_active
    ON user_tenant_access(user_id, tenant_id)
    WHERE expires_at IS NULL OR expires_at > NOW();

-- ============================================================================
-- Tenant Tools Table
-- ============================================================================

CREATE TABLE tenant_tools (
    id SERIAL PRIMARY KEY,

    -- Tenant reference
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenant_configs(tenant_id) ON DELETE CASCADE,

    -- Tool identification
    tool_name VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',

    -- Status
    enabled BOOLEAN DEFAULT TRUE,

    -- Access control
    required_access_level VARCHAR(16) NOT NULL DEFAULT 'read'
        CHECK (required_access_level IN ('read', 'write', 'admin')),

    -- Rate limiting (requests per minute, NULL = unlimited)
    rate_limit INTEGER DEFAULT NULL CHECK (rate_limit IS NULL OR rate_limit > 0),

    -- Which credential keys from tenant_configs.credentials this tool needs
    credential_keys TEXT[] DEFAULT '{}',

    -- Additional tool configuration
    tool_config JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: tool name must be unique per tenant
    UNIQUE(tenant_id, tool_name)
);

-- Index for listing tools by tenant
CREATE INDEX idx_tenant_tools_tenant_id ON tenant_tools(tenant_id);

-- Index for finding enabled tools
CREATE INDEX idx_tenant_tools_enabled ON tenant_tools(tenant_id, enabled) WHERE enabled = TRUE;

-- Trigger to auto-update updated_at
CREATE TRIGGER update_tenant_tools_updated_at
    BEFORE UPDATE ON tenant_tools
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Audit Log Table
-- ============================================================================

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,

    -- Event timestamp
    timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Who performed the action
    user_id VARCHAR(255) NOT NULL,

    -- What tenant context
    tenant_id VARCHAR(64) REFERENCES tenant_configs(tenant_id) ON DELETE SET NULL,

    -- Action details
    action VARCHAR(64) NOT NULL,  -- "tool_execute", "tool_list", "access_grant", etc.
    resource_type VARCHAR(64),    -- "tool", "tenant", "access"
    resource_id VARCHAR(255),     -- Specific resource identifier

    -- Request/response data (for compliance)
    request_data JSONB DEFAULT '{}',
    response_summary JSONB DEFAULT '{}',  -- Summary only, not full response

    -- Outcome
    success BOOLEAN NOT NULL,
    error_message TEXT DEFAULT NULL,

    -- Client info
    client_ip INET,
    user_agent TEXT,

    -- Correlation
    request_id UUID DEFAULT uuid_generate_v4()
);

-- Partition audit logs by month for performance
-- (Implement partitioning based on timestamp in production)

-- Index for querying by user
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id, timestamp DESC);

-- Index for querying by tenant
CREATE INDEX idx_audit_logs_tenant_id ON audit_logs(tenant_id, timestamp DESC);

-- Index for querying by action
CREATE INDEX idx_audit_logs_action ON audit_logs(action, timestamp DESC);

-- Index for error analysis
CREATE INDEX idx_audit_logs_errors ON audit_logs(timestamp DESC) WHERE success = FALSE;

-- ============================================================================
-- SSO Group Mapping Table (for automatic access sync)
-- ============================================================================

CREATE TABLE sso_group_mappings (
    id SERIAL PRIMARY KEY,

    -- SSO group identifier (from Azure AD, Okta, etc.)
    sso_group_id VARCHAR(255) NOT NULL,
    sso_group_name VARCHAR(255),

    -- Maps to tenant access
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenant_configs(tenant_id) ON DELETE CASCADE,
    access_level VARCHAR(16) NOT NULL CHECK (access_level IN ('read', 'write', 'admin')),

    -- SSO provider
    sso_provider VARCHAR(64) NOT NULL,  -- "azure_ad", "okta", "keycloak"

    -- Status
    enabled BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: SSO group maps to only one tenant
    UNIQUE(sso_provider, sso_group_id)
);

-- Index for looking up mappings by SSO group
CREATE INDEX idx_sso_group_mappings_group ON sso_group_mappings(sso_provider, sso_group_id);

-- ============================================================================
-- Rate Limiting Table
-- ============================================================================

CREATE TABLE rate_limit_counters (
    id SERIAL PRIMARY KEY,

    -- Rate limit key (composite of user, tenant, tool)
    rate_key VARCHAR(512) NOT NULL,

    -- Counter window
    window_start TIMESTAMPTZ NOT NULL,
    window_duration_seconds INTEGER NOT NULL DEFAULT 60,

    -- Request count in current window
    request_count INTEGER NOT NULL DEFAULT 0,

    -- Unique constraint for upsert operations
    UNIQUE(rate_key, window_start)
);

-- Index for cleanup of old windows
CREATE INDEX idx_rate_limit_counters_window ON rate_limit_counters(window_start);

-- ============================================================================
-- Views for Common Queries
-- ============================================================================

-- View: Active user tenant access (excludes expired)
CREATE VIEW v_active_user_tenant_access AS
SELECT
    uta.id,
    uta.user_id,
    uta.tenant_id,
    tc.display_name AS tenant_display_name,
    uta.access_level,
    uta.source,
    uta.granted_at,
    uta.expires_at
FROM user_tenant_access uta
JOIN tenant_configs tc ON uta.tenant_id = tc.tenant_id
WHERE tc.enabled = TRUE
  AND (uta.expires_at IS NULL OR uta.expires_at > NOW());

-- View: Available tools per tenant
CREATE VIEW v_tenant_available_tools AS
SELECT
    tt.id,
    tt.tenant_id,
    tc.display_name AS tenant_display_name,
    tt.tool_name,
    tt.display_name AS tool_display_name,
    tt.description,
    tt.required_access_level,
    tt.rate_limit
FROM tenant_tools tt
JOIN tenant_configs tc ON tt.tenant_id = tc.tenant_id
WHERE tt.enabled = TRUE
  AND tc.enabled = TRUE;

-- ============================================================================
-- Sample Data for Development
-- ============================================================================

-- Insert sample tenants
INSERT INTO tenant_configs (tenant_id, display_name, description, mcp_endpoint, mcp_api_key_ref, credentials) VALUES
('google', 'Google', 'Google Cloud Platform client', 'http://mcp-google:8001', 'vault:secret/mcp/google/api-key',
 '{"jira_token": "vault:secret/mcp/google/jira", "jira_url": "https://google.atlassian.net"}'::jsonb),
('microsoft', 'Microsoft', 'Microsoft Azure client', 'http://mcp-microsoft:8001', 'vault:secret/mcp/microsoft/api-key',
 '{"jira_token": "vault:secret/mcp/microsoft/jira", "jira_url": "https://microsoft.atlassian.net"}'::jsonb),
('company-c', 'Company C', 'Example client C', 'http://mcp-company-c:8001', 'vault:secret/mcp/company-c/api-key',
 '{"jira_token": "vault:secret/mcp/company-c/jira"}'::jsonb);

-- Insert sample user access
INSERT INTO user_tenant_access (user_id, tenant_id, access_level, granted_by, source) VALUES
('internal.user@company.com', 'google', 'write', 'admin@company.com', 'manual'),
('internal.user@company.com', 'microsoft', 'read', 'admin@company.com', 'manual'),
('google.employee@google.com', 'google', 'write', 'admin@company.com', 'sso_group'),
('ms.employee@microsoft.com', 'microsoft', 'write', 'admin@company.com', 'sso_group');

-- Insert sample tools
INSERT INTO tenant_tools (tenant_id, tool_name, display_name, description, required_access_level, credential_keys) VALUES
('google', 'jira_list_issues', 'List Jira Issues', 'List issues from Jira project', 'read', ARRAY['jira_token', 'jira_url']),
('google', 'jira_create_issue', 'Create Jira Issue', 'Create a new Jira issue', 'write', ARRAY['jira_token', 'jira_url']),
('google', 'confluence_search', 'Search Confluence', 'Search Confluence pages', 'read', ARRAY['jira_token', 'jira_url']),
('microsoft', 'jira_list_issues', 'List Jira Issues', 'List issues from Jira project', 'read', ARRAY['jira_token', 'jira_url']),
('microsoft', 'jira_create_issue', 'Create Jira Issue', 'Create a new Jira issue', 'write', ARRAY['jira_token', 'jira_url']);
```

---

## 4. API Endpoints

### 4.1 Tool Discovery

#### GET /tools

List all tools available to the current user based on their tenant access.

**Authentication:** Bearer JWT (from Open WebUI SSO)

**Request:**
```http
GET /tools HTTP/1.1
Host: mcp-proxy.company.com
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "tools": [
    {
      "tenant_id": "google",
      "tenant_display_name": "Google",
      "tool_name": "jira_list_issues",
      "display_name": "List Jira Issues",
      "description": "List issues from Jira project",
      "required_access_level": "read",
      "parameters": {
        "type": "object",
        "properties": {
          "project_key": {
            "type": "string",
            "description": "Jira project key"
          }
        }
      }
    },
    {
      "tenant_id": "google",
      "tenant_display_name": "Google",
      "tool_name": "jira_create_issue",
      "display_name": "Create Jira Issue",
      "description": "Create a new Jira issue",
      "required_access_level": "write",
      "parameters": {...}
    },
    {
      "tenant_id": "microsoft",
      "tenant_display_name": "Microsoft",
      "tool_name": "jira_list_issues",
      "display_name": "List Jira Issues",
      "description": "List issues from Jira project",
      "required_access_level": "read",
      "parameters": {...}
    }
  ],
  "user_id": "internal.user@company.com",
  "tenant_access": [
    {"tenant_id": "google", "access_level": "write"},
    {"tenant_id": "microsoft", "access_level": "read"}
  ]
}
```

**Error Responses:**
- `401 Unauthorized` - Invalid or missing JWT
- `403 Forbidden` - User has no tenant access

---

### 4.2 Tool Execution

#### POST /tools/{tenant_id}/{tool_name}/execute

Execute a specific tool with tenant-specific credentials injected.

**Authentication:** Bearer JWT (from Open WebUI SSO)

**Path Parameters:**
- `tenant_id` - Target tenant (e.g., "google")
- `tool_name` - Tool to execute (e.g., "jira_create_issue")

**Request:**
```http
POST /tools/google/jira_create_issue/execute HTTP/1.1
Host: mcp-proxy.company.com
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "arguments": {
    "project_key": "PROJ",
    "summary": "Bug: Login button not working",
    "description": "Users cannot click the login button on mobile",
    "issue_type": "Bug"
  }
}
```

**Response (Success):**
```json
{
  "success": true,
  "result": {
    "issue_key": "PROJ-1234",
    "issue_url": "https://google.atlassian.net/browse/PROJ-1234",
    "created_at": "2026-01-06T10:30:00Z"
  },
  "execution_time_ms": 245,
  "tenant_id": "google",
  "tool_name": "jira_create_issue"
}
```

**Response (Error):**
```json
{
  "success": false,
  "error": {
    "code": "UPSTREAM_ERROR",
    "message": "Jira API returned 400: Project PROJ does not exist",
    "details": {...}
  },
  "execution_time_ms": 120,
  "tenant_id": "google",
  "tool_name": "jira_create_issue"
}
```

**Error Responses:**
- `401 Unauthorized` - Invalid or missing JWT
- `403 Forbidden` - User does not have access to this tenant or insufficient access level
- `404 Not Found` - Tenant or tool not found
- `429 Too Many Requests` - Rate limit exceeded
- `502 Bad Gateway` - Upstream MCP server error

---

### 4.3 Tenant Discovery

#### GET /tenants

List all tenants the current user has access to.

**Authentication:** Bearer JWT (from Open WebUI SSO)

**Request:**
```http
GET /tenants HTTP/1.1
Host: mcp-proxy.company.com
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "tenants": [
    {
      "tenant_id": "google",
      "display_name": "Google",
      "description": "Google Cloud Platform client",
      "access_level": "write",
      "tool_count": 3,
      "granted_at": "2025-06-15T09:00:00Z",
      "source": "manual"
    },
    {
      "tenant_id": "microsoft",
      "display_name": "Microsoft",
      "description": "Microsoft Azure client",
      "access_level": "read",
      "tool_count": 2,
      "granted_at": "2025-08-20T14:30:00Z",
      "source": "sso_group"
    }
  ],
  "user_id": "internal.user@company.com"
}
```

---

### 4.4 Health & Metrics

#### GET /health

Health check endpoint for Kubernetes probes.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "dependencies": {
    "database": "healthy",
    "vault": "healthy",
    "mcp_google": "healthy",
    "mcp_microsoft": "healthy"
  },
  "uptime_seconds": 86400
}
```

#### GET /metrics

Prometheus metrics endpoint.

```
# HELP mcp_proxy_requests_total Total number of requests
# TYPE mcp_proxy_requests_total counter
mcp_proxy_requests_total{tenant="google",tool="jira_create_issue",status="success"} 1234
mcp_proxy_requests_total{tenant="microsoft",tool="jira_list_issues",status="success"} 5678

# HELP mcp_proxy_request_duration_seconds Request duration in seconds
# TYPE mcp_proxy_request_duration_seconds histogram
mcp_proxy_request_duration_seconds_bucket{tenant="google",le="0.1"} 100
mcp_proxy_request_duration_seconds_bucket{tenant="google",le="0.5"} 450
```

---

## 5. Authentication Flow

### 5.1 JWT Validation Sequence

```
┌─────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────┐
│  User   │     │  Open WebUI │     │ MCP Proxy    │     │ MCP     │
│ Browser │     │             │     │ Gateway      │     │ Server  │
└────┬────┘     └──────┬──────┘     └──────┬───────┘     └────┬────┘
     │                 │                    │                  │
     │  1. Login (SSO) │                    │                  │
     │────────────────▶│                    │                  │
     │                 │                    │                  │
     │  2. JWT Token   │                    │                  │
     │◀────────────────│                    │                  │
     │                 │                    │                  │
     │  3. Use Tool    │                    │                  │
     │────────────────▶│                    │                  │
     │                 │                    │                  │
     │                 │  4. Forward + JWT  │                  │
     │                 │───────────────────▶│                  │
     │                 │                    │                  │
     │                 │                    │  5. Validate JWT │
     │                 │                    │  (JWKS endpoint) │
     │                 │                    │                  │
     │                 │                    │  6. Extract user │
     │                 │                    │  from JWT claims │
     │                 │                    │                  │
     │                 │                    │  7. Query tenant │
     │                 │                    │  access from DB  │
     │                 │                    │                  │
     │                 │                    │  8. Verify access│
     │                 │                    │  to requested    │
     │                 │                    │  tenant/tool     │
     │                 │                    │                  │
     │                 │                    │  9. Inject creds │
     │                 │                    │───────────────────▶│
     │                 │                    │                    │
     │                 │                    │  10. Execute tool  │
     │                 │                    │◀───────────────────│
     │                 │                    │                    │
     │                 │  11. Result        │                    │
     │                 │◀───────────────────│                    │
     │                 │                    │                    │
     │  12. Result     │                    │                    │
     │◀────────────────│                    │                    │
```

### 5.2 JWT Claims Structure

Expected JWT payload from SSO provider (Azure AD example):

```json
{
  "iss": "https://login.microsoftonline.com/{tenant-id}/v2.0",
  "sub": "user_unique_id",
  "aud": "client_id_of_open_webui",
  "exp": 1735989600,
  "iat": 1735986000,
  "email": "john.doe@company.com",
  "name": "John Doe",
  "preferred_username": "john.doe@company.com",
  "groups": [
    "google-team-group-id",
    "all-employees-group-id"
  ],
  "roles": ["user"]
}
```

### 5.3 User Identification Strategy

1. **Primary:** Use `email` claim as `user_id`
2. **Fallback:** Use `preferred_username` if `email` not present
3. **Last resort:** Use `sub` claim (opaque ID)

```python
def extract_user_id(jwt_payload: dict) -> str:
    """Extract user identifier from JWT claims."""
    return (
        jwt_payload.get("email") or
        jwt_payload.get("preferred_username") or
        jwt_payload.get("sub")
    )
```

### 5.4 Group-Based Access Sync

For SSO group to tenant mapping:

```python
async def sync_user_access_from_groups(user_id: str, sso_groups: list[str]):
    """
    Sync user's tenant access based on SSO group membership.
    Called after JWT validation.
    """
    # Get group-to-tenant mappings
    mappings = await db.query("""
        SELECT tenant_id, access_level
        FROM sso_group_mappings
        WHERE sso_group_id = ANY($1) AND enabled = TRUE
    """, sso_groups)

    for mapping in mappings:
        # Upsert access if from SSO (won't overwrite manual grants)
        await db.execute("""
            INSERT INTO user_tenant_access
                (user_id, tenant_id, access_level, granted_by, source)
            VALUES ($1, $2, $3, 'sso_sync', 'sso_group')
            ON CONFLICT (user_id, tenant_id)
            DO UPDATE SET access_level = $3, granted_by = 'sso_sync'
            WHERE user_tenant_access.source = 'sso_group'
        """, user_id, mapping.tenant_id, mapping.access_level)
```

---

## 6. Credential Injection

### 6.1 Credential Resolution Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Credential Injector                          │
└─────────────────────────────────────────────────────────────────────┘
     │
     │  1. Get tenant config from DB
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  tenant_configs.credentials = {                                      │
│    "jira_token": "vault:secret/mcp/google/jira",                     │
│    "jira_url": "https://google.atlassian.net"                        │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
     │
     │  2. Get required credentials for tool
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  tenant_tools.credential_keys = ["jira_token", "jira_url"]           │
└─────────────────────────────────────────────────────────────────────┘
     │
     │  3. Resolve Vault references
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HashiCorp Vault                                                     │
│  GET /v1/secret/data/mcp/google/jira                                 │
│  → {"data": {"value": "actual_api_token_here"}}                      │
└─────────────────────────────────────────────────────────────────────┘
     │
     │  4. Inject into MCP request
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Outgoing MCP Request:                                               │
│  POST /tools/jira_create_issue/execute                               │
│  Authorization: Bearer <mcpo_api_key>                                │
│  Body: {                                                             │
│    "arguments": {...user_provided...},                               │
│    "_credentials": {                                                 │
│      "jira_token": "actual_api_token_here",                          │
│      "jira_url": "https://google.atlassian.net"                      │
│    }                                                                 │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Vault Integration Code

```python
import hvac
from functools import lru_cache

class VaultClient:
    def __init__(self, vault_addr: str, vault_token: str):
        self.client = hvac.Client(url=vault_addr, token=vault_token)

    @lru_cache(maxsize=1000, ttl=300)  # Cache for 5 minutes
    def get_secret(self, path: str) -> str:
        """
        Retrieve a secret from Vault.
        Path format: "vault:secret/mcp/google/jira"
        """
        if not path.startswith("vault:"):
            # Not a Vault reference, return as-is
            return path

        vault_path = path.replace("vault:", "")
        response = self.client.secrets.kv.v2.read_secret_version(
            path=vault_path,
            mount_point="secret"
        )
        return response["data"]["data"]["value"]


async def inject_credentials(
    tenant_config: TenantConfig,
    tool_config: TenantTools,
    vault: VaultClient
) -> dict:
    """
    Resolve and inject credentials for a tool execution.
    Returns dict of credential key -> resolved value.
    """
    credentials = {}

    for key in tool_config.credential_keys:
        if key in tenant_config.credentials:
            raw_value = tenant_config.credentials[key]
            credentials[key] = vault.get_secret(raw_value)

    return credentials
```

### 6.3 Credential Security Best Practices

1. **Never log credentials** - Redact in all log messages
2. **Short TTL caching** - Cache resolved credentials for max 5 minutes
3. **Vault token rotation** - Use Kubernetes auth method for auto-rotation
4. **Network isolation** - Vault accessible only from proxy gateway
5. **Audit trail** - Log which credentials were accessed (but not values)

---

## 7. Security Considerations

### 7.1 Encryption

| Data | At Rest | In Transit |
|------|---------|------------|
| JWT Tokens | N/A (short-lived) | TLS 1.3 |
| API Keys in Vault | AES-256-GCM | TLS 1.3 |
| Database | Transparent Data Encryption | TLS 1.3 |
| Audit Logs | Encrypted volume | TLS 1.3 |

### 7.2 Vault Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐         ┌─────────────────────────────────────┐│
│  │ MCP Proxy       │         │ HashiCorp Vault                     ││
│  │ Gateway Pod     │         │                                     ││
│  │                 │ ◀──────▶│ Auth: Kubernetes Service Account    ││
│  │ ServiceAccount: │         │ Policy: mcp-proxy-read              ││
│  │ mcp-proxy       │         │                                     ││
│  └─────────────────┘         │ Secrets:                            ││
│                              │   secret/mcp/google/*               ││
│                              │   secret/mcp/microsoft/*            ││
│                              │   secret/mcp/company-c/*            ││
│                              └─────────────────────────────────────┘│
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Vault Policy (mcp-proxy-read):**
```hcl
path "secret/data/mcp/*" {
  capabilities = ["read"]
}

path "secret/metadata/mcp/*" {
  capabilities = ["list"]
}
```

### 7.3 Audit Logging Requirements

All tool executions must be logged with:

| Field | Description | Example |
|-------|-------------|---------|
| timestamp | UTC timestamp | 2026-01-06T10:30:00Z |
| request_id | Unique correlation ID | uuid |
| user_id | User who made request | john.doe@company.com |
| tenant_id | Target tenant | google |
| tool_name | Tool executed | jira_create_issue |
| action | What was done | tool_execute |
| success | Outcome | true/false |
| client_ip | Source IP | 10.0.1.50 |
| request_summary | Sanitized request | {"project": "PROJ"} |
| response_code | HTTP status | 200 |
| duration_ms | Execution time | 245 |

**Audit Log Retention:**
- Hot storage: 30 days (PostgreSQL)
- Warm storage: 1 year (S3/GCS)
- Cold archive: 7 years (compliance)

### 7.4 Network Security

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Kubernetes Network Policies                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐                                                    │
│  │ Ingress      │  Only from: Open WebUI pods                       │
│  │ Controller   │  Port: 443                                         │
│  └──────┬───────┘                                                    │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────┐                                                    │
│  │ MCP Proxy    │  Egress to: Vault, PostgreSQL, MCP servers        │
│  │ Gateway      │  No internet access                                │
│  └──────┬───────┘                                                    │
│         │                                                            │
│    ┌────┴────┬─────────────┐                                         │
│    ▼         ▼             ▼                                         │
│  ┌─────┐  ┌──────┐  ┌────────────┐                                   │
│  │Vault│  │ PG   │  │MCP Servers │  Only from: MCP Proxy             │
│  └─────┘  └──────┘  └────────────┘  No external access              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.5 Rate Limiting

Per-user, per-tenant, per-tool rate limits:

```python
async def check_rate_limit(
    user_id: str,
    tenant_id: str,
    tool_name: str,
    limit: int  # requests per minute
) -> bool:
    """
    Check if request is within rate limit.
    Uses sliding window algorithm.
    """
    rate_key = f"{user_id}:{tenant_id}:{tool_name}"
    window_start = datetime.now().replace(second=0, microsecond=0)

    result = await db.execute("""
        INSERT INTO rate_limit_counters (rate_key, window_start, request_count)
        VALUES ($1, $2, 1)
        ON CONFLICT (rate_key, window_start)
        DO UPDATE SET request_count = rate_limit_counters.request_count + 1
        RETURNING request_count
    """, rate_key, window_start)

    return result["request_count"] <= limit
```

### 7.6 Input Validation

All inputs must be validated:

```python
from pydantic import BaseModel, validator
import re

class ToolExecuteRequest(BaseModel):
    arguments: dict

    @validator('arguments')
    def validate_arguments(cls, v):
        # Prevent injection attacks
        json_str = json.dumps(v)
        if len(json_str) > 100_000:  # 100KB max
            raise ValueError("Arguments too large")
        return v

class TenantIdPath(BaseModel):
    tenant_id: str

    @validator('tenant_id')
    def validate_tenant_id(cls, v):
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', v):
            raise ValueError("Invalid tenant_id format")
        if len(v) > 64:
            raise ValueError("tenant_id too long")
        return v
```

---

## 8. Deployment Architecture

### 8.1 Kubernetes Resources

```yaml
# High-level Kubernetes resource overview
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-proxy-gateway
spec:
  replicas: 3  # HA deployment
  selector:
    matchLabels:
      app: mcp-proxy-gateway
  template:
    spec:
      serviceAccountName: mcp-proxy  # For Vault auth
      containers:
      - name: mcp-proxy
        image: company/mcp-proxy-gateway:1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: mcp-proxy-secrets
              key: database-url
        - name: VAULT_ADDR
          value: "http://vault.vault.svc:8200"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
```

### 8.2 Scaling Considerations

| Component | Scaling Strategy | Target |
|-----------|------------------|--------|
| MCP Proxy Gateway | HPA based on CPU/requests | 3-10 pods |
| PostgreSQL | Managed (RDS/Cloud SQL) | Single primary + read replicas |
| Vault | HA cluster | 3 nodes |
| MCP Servers | HPA per tenant | 1-5 pods per tenant |

---

## 9. Implementation Roadmap

### Phase 1: Core Proxy (Week 1)
- [ ] FastAPI skeleton with JWT validation
- [ ] PostgreSQL schema deployment
- [ ] Basic tool listing endpoint
- [ ] Basic tool execution endpoint

### Phase 2: Credential Management (Week 2)
- [ ] Vault integration
- [ ] Credential injection
- [ ] Credential caching

### Phase 3: Security Hardening (Week 3)
- [ ] Rate limiting
- [ ] Audit logging
- [ ] Input validation
- [ ] Network policies

### Phase 4: Production Deployment (Week 4)
- [ ] Kubernetes manifests
- [ ] Helm chart
- [ ] Monitoring/alerting
- [ ] Documentation

---

## 10. References

- [Open WebUI MCP Documentation](https://docs.openwebui.com/features/mcp/)
- [mcpo GitHub Repository](https://github.com/open-webui/mcpo)
- [HashiCorp Vault Kubernetes Auth](https://developer.hashicorp.com/vault/docs/auth/kubernetes)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Multi-Tenant MCP Research](./2026-01-06-multi-tenant-mcp-research.md)
