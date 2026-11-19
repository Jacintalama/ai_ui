-- Rolls back 070. Applied by hand. Keys made for n8n ({tools}) would then
-- read as agent keys, so revoke them FIRST:
--   UPDATE tasks.automation_key SET revoked_at = now()
--    WHERE revoked_at IS NULL AND NOT ('agents' = ANY(scopes));
ALTER TABLE tasks.automation_key DROP COLUMN IF EXISTS n8n_credential_id;
ALTER TABLE tasks.automation_key DROP COLUMN IF EXISTS allowed_writes;
ALTER TABLE tasks.automation_key DROP COLUMN IF EXISTS scopes;
