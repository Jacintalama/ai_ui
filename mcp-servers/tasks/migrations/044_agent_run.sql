-- 044: when each agent actually ran, and for how long.
--
-- Nothing recorded this. A schedule kept last_run_at and last_run_status, but
-- that describes the SCHEDULE, not the agent, and an agent someone mentioned
-- in a channel left no trace at all. So there was no way to answer "is this
-- thing doing anything right now" or "how long did that take", which is what
-- the cards on the Agents page now show.
--
-- One row per run, from any source: a cron schedule, a mention in a channel,
-- or a run started by hand. `source` is what makes the card able to say where
-- the work came from rather than just that it happened.
--
-- finished_at NULL means still running. It is not a promise: a process that
-- dies mid run never writes the finish, so a row can sit unfinished forever.
-- Readers must treat an old unfinished row as failed rather than as an agent
-- that has been awake for three days. The scheduler already learned this the
-- hard way with last_run_status='running', which wedged run-now permanently
-- when a run crashed.
--
-- No foreign key to public.model: Open WebUI owns that table and an agent can
-- be deleted at any moment. Losing the history of what an agent did the
-- instant it is deleted would be worse than keeping rows that point at
-- nothing, and a cascade would do exactly that.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.agent_run (
    id          UUID        PRIMARY KEY,
    agent_id    TEXT        NOT NULL,
    user_email  TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT
);

-- The card asks "the most recent run for each of my agents", so the index
-- carries the owner and the ordering it reads by.
CREATE INDEX IF NOT EXISTS agent_run_owner_recent_idx
    ON tasks.agent_run (user_email, agent_id, started_at DESC);
