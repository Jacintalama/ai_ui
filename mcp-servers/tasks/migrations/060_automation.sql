-- 060: Automations (automations.py, automation_runner.py, routes_automations.py).
--
-- One row is one rule a person set up: when this happens, this agent does
-- this, and the result goes there. The first trigger is a webhook: every
-- automation has a secret URL (hook_token) that anything can POST to, with
-- or without a body, and the agent runs on what was posted. A schedule
-- stays in tasks.schedules; an email trigger comes next and will add a
-- trigger kind here.
--
-- automation_run keeps the last runs for the page: what started it, what
-- came out, and whether it was delivered.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.automation (
    id            UUID PRIMARY KEY,
    user_email    TEXT NOT NULL,
    name          TEXT NOT NULL,
    -- The agent that does the work; checked at run time, never a foreign
    -- key, because Open WebUI owns the model table.
    agent_id      TEXT NOT NULL,
    -- What to tell the agent. What was posted is put after it.
    instructions  TEXT NOT NULL,
    trigger       TEXT NOT NULL DEFAULT 'webhook',
    -- The secret in the webhook URL. Unique so a POST finds its row.
    hook_token    TEXT NOT NULL UNIQUE,
    -- chat (the agent's private conversation in the office), discord (the
    -- person's schedules thread), none (the caller reads the reply).
    deliver_to    TEXT NOT NULL DEFAULT 'chat',
    enabled       BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at   TIMESTAMPTZ,
    last_status   TEXT,
    run_count     INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS automation_owner
    ON tasks.automation (user_email, created_at DESC);

CREATE TABLE IF NOT EXISTS tasks.automation_run (
    id             UUID PRIMARY KEY,
    automation_id  UUID NOT NULL,
    user_email     TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    -- done, failed, skipped
    status         TEXT NOT NULL,
    -- The start of what was posted, so the page can say what set it off.
    trigger_text   TEXT NOT NULL DEFAULT '',
    result         TEXT NOT NULL DEFAULT '',
    delivered      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS automation_run_recent
    ON tasks.automation_run (automation_id, started_at DESC);
