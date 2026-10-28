-- 062: Events out (events_out.py, routes_events.py).
--
-- A URL a person sets, and the platform POSTs to it when something of
-- theirs happens: a build finished, a scheduled run ended, an automation
-- ran, an agent stopped to ask, a question was answered, minutes were
-- taken. n8n and any other system can react. Each hook has a secret the
-- body is signed with (HMAC-SHA256 in X-IO-Signature), so the receiver
-- can tell the platform's posts from anybody's.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.event_hook (
    id            UUID PRIMARY KEY,
    user_email    TEXT NOT NULL,
    url           TEXT NOT NULL,
    secret        TEXT NOT NULL,
    -- The events to send, as a JSON list of names; ["*"] is all of them.
    events        JSONB NOT NULL DEFAULT '["*"]'::jsonb,
    label         TEXT NOT NULL DEFAULT '',
    enabled       BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sent_at  TIMESTAMPTZ,
    -- ok, or the status code or a short reason of the last failure.
    last_result   TEXT NOT NULL DEFAULT '',
    fail_count    INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS event_hook_owner
    ON tasks.event_hook (user_email, created_at DESC);
