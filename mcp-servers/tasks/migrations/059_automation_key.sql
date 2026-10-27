-- 059: Automation keys (automation_keys.py, routes_automation.py).
--
-- A key a person makes on the Agents page so that something off the box,
-- an n8n workflow first of all, can run one of their agents through
-- POST /api/tasks/agents/run without a signed-in session. Only the hash is
-- kept: the key is shown once when it is made and never again.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.automation_key (
    id           UUID PRIMARY KEY,
    user_email   TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    -- sha256 of the key, hex. Looked up on every run.
    key_hash     TEXT NOT NULL UNIQUE,
    -- The first characters of the key, so the owner can tell keys apart.
    prefix       TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS automation_key_owner
    ON tasks.automation_key (user_email, created_at DESC);
