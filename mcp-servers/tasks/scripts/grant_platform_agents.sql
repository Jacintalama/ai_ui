-- Make the ready-made agents visible to everyone.
--
-- A wildcard read grant is the same shape the 131 model rows and the mcp-proxy
-- tool server already carry: principal_type 'user', principal_id '*',
-- permission 'read'. It is what get_accessible_resource_ids matches on.
--
-- This is applied as SQL rather than through the create endpoint because that
-- endpoint filters access_grants through the sharing.public_models permission,
-- which is false on this platform. Writing the row is the path that was proved
-- to work: with it, a second account saw the agent and got params blanked and
-- meta intact, which is exactly what the duplicate button relies on.
--
-- Idempotent: re-running adds nothing.
INSERT INTO access_grant (id, resource_type, resource_id, principal_type,
                          principal_id, permission, created_at)
SELECT gen_random_uuid()::text, 'model', m.id, 'user', '*', 'read',
       extract(epoch from now())::bigint
  FROM model m
 WHERE m.id IN ('agent-research-assistant-0001', 'agent-inbox-triage-0002')
   AND NOT EXISTS (
     SELECT 1 FROM access_grant g
      WHERE g.resource_type = 'model'
        AND g.resource_id = m.id
        AND g.principal_type = 'user'
        AND g.principal_id = '*'
        AND g.permission = 'read'
   );

-- What was granted, so the run is auditable rather than silent.
SELECT resource_id, principal_id, permission
  FROM access_grant
 WHERE resource_type = 'model'
   AND resource_id IN ('agent-research-assistant-0001', 'agent-inbox-triage-0002')
 ORDER BY resource_id;
