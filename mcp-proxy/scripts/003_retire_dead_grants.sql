-- 003: retire grant data that names things which do not exist.
--
-- Run once, by hand, against the mcp_proxy schema. Idempotent.
--
-- Context: access resolution now intersects every answer with the enabled
-- server registry (tenants.resolve_user_servers), so the rows below already
-- grant nothing. This removes them so the admin portal shows what is true
-- instead of showing grants that silently evaporate.
--
-- 1. user_server_access: 22 rows, read by NO code. Verified by grep across the
--    repo and inside the mcp-proxy, tasks, api-gateway and webhook-handler
--    containers. Its contents duplicate what group_tenant_mapping already
--    grants the same four accounts, and mostly name disabled servers.
--
--    RENAMED rather than dropped. Nothing reads it, so a drop is safe on the
--    evidence, but a rename costs nothing, keeps the 22 rows recoverable, and
--    turns "something did read it after all" into a loud failure instead of a
--    silent empty result.
--
-- 2. group_tenant_mapping rows naming linear, atlassian, slack, gitlab and
--    hubspot. None of those five were ever deployed: they are in no compose
--    file and have no container. The mapping was written for a server list
--    that never shipped, which is why every non-admin resolved to nothing.
--
--    The three largest servers that DO exist (clickup 172 tools, trello 25,
--    n8n 20) are deliberately NOT added here. They run on one shared vendor
--    token, so a grant means acting as the platform's own account. They stay
--    off until a user connects their own credential.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'mcp_proxy'
                 AND table_name = 'user_server_access') THEN
        ALTER TABLE mcp_proxy.user_server_access
            RENAME TO user_server_access_retired_20260819;
    END IF;
END $$;

DELETE FROM mcp_proxy.group_tenant_mapping
 WHERE tenant_id IN ('linear', 'atlassian', 'slack', 'gitlab', 'hubspot');
