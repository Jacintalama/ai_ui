-- 043: who has already been given their own copy of the starter agents.
--
-- One row per user, written after their copies are created. Its only job is
-- to make a DELETE stick: without it, the next page load would helpfully
-- recreate the agents the user just threw away, and they could never be rid
-- of them.
--
-- Keyed by email because that is the identity the web path carries
-- (X-User-Email, injected by the gateway) and the same key
-- tasks.user_connections uses.
--
-- No foreign key to public.user: Open WebUI owns that table, and a deleted
-- account should not block or cascade into this record.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.agent_seed (
    user_email TEXT        PRIMARY KEY,
    seeded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
