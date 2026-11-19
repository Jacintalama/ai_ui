-- 070: what an automation key may do (automation_keys.py, routes_tool_run.py).
--
-- Until 2026-11-19 an iok_ key did one thing: run the owner's agents through
-- POST /api/tasks/agents/run. n8n now gets a second door, running ONE tool
-- with the person's own connection (POST /api/tasks/tools/run), and a key
-- somebody made to run agents must not quietly gain it. So:
--
--   scopes             'agents' and/or 'tools'. Every key that exists today
--                      becomes {agents}, exactly what it could do before.
--   allowed_writes     'app.tool' entries. A tools key runs any READ tool,
--                      but a WRITE only once the person approved a workflow
--                      AIUI built with that step in it.
--   n8n_credential_id  the credential in the person's n8n that holds this
--                      key, so AIUI reuses it instead of minting one per
--                      workflow.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
ALTER TABLE tasks.automation_key
    ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT '{agents}';
ALTER TABLE tasks.automation_key
    ADD COLUMN IF NOT EXISTS allowed_writes TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tasks.automation_key
    ADD COLUMN IF NOT EXISTS n8n_credential_id TEXT;
