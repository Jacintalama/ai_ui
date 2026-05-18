-- Migration: create user_tenant_access table for per-user MCP tenant grants.
--
-- The mcp-proxy auth model has 3 priorities for granting tenant access:
--   0. MCP-Admin group (grants all tenants)
--   1. Group-based via mcp_proxy.group_tenant_mapping
--   2. Direct per-user via mcp_proxy.user_tenant_access  ← THIS TABLE
--
-- Without this table, every Priority-2 query raised
-- "relation user_tenant_access does not exist", the exception handler
-- returned False (deny), and any user without MCP-Admin or matching
-- group mapping was 403'd for every tenant — including the scheduler.
--
-- Discovered when user ralphbenitez32@gmail.com tried to ask "is any
-- cron active" in Open WebUI chat and got 403 from list_cron_jobs.
-- The mcp-scheduler tenant has `groups: ["MCP-Admin"]` so non-admins
-- needed the user_tenant_access path, which was broken.
--
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS mcp_proxy.user_tenant_access (
  user_email   VARCHAR(255) NOT NULL,
  tenant_id    VARCHAR(255) NOT NULL,
  access_level VARCHAR(50)  NOT NULL DEFAULT 'read',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_email, tenant_id)
);

-- Functional index on lowered email — matches the LOWER(user_email) in
-- mcp-proxy/db.py's queries.
CREATE INDEX IF NOT EXISTS idx_user_tenant_access_email
  ON mcp_proxy.user_tenant_access(LOWER(user_email));

CREATE INDEX IF NOT EXISTS idx_user_tenant_access_tenant
  ON mcp_proxy.user_tenant_access(tenant_id);
