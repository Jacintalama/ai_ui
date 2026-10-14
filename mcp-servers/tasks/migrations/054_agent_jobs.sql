-- 054: agent team jobs, a request split into steps for several agents.
--
-- A message to the whole team that is really several pieces of work gets a
-- plan from the lead agent. The person presses Start, and a background worker
-- runs the steps one at a time, so the job outlives the page that asked for
-- it and the process that was running it. These two tables are what make it
-- outlive them: every step's state and result is written as it happens, and
-- the worker reads them back after a restart (agent_job_store).
-- See docs/plans/2026-10-14-agent-team-jobs-design.md.
--
-- TEXT ids, not UUID: they are created in Python and travel through URLs and
-- the live feed as strings, and nothing ever compares them as UUIDs.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.

CREATE TABLE IF NOT EXISTS tasks.agent_job (
    id            TEXT PRIMARY KEY,
    user_email    TEXT NOT NULL,
    -- The conversation the plan card was posted in. NULL only if the room
    -- had not been saved yet when the plan was made.
    chat_id       TEXT,
    lead_agent_id TEXT NOT NULL,
    request       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'proposed'
                  CHECK (status IN ('proposed','running','needs_you','done',
                                    'failed','cancelled')),
    -- The lead's final answer, once the job is done.
    result        TEXT,
    -- Whether the person has looked since the job ended: the Done badge.
    seen          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS agent_job_user_status
    ON tasks.agent_job (user_email, status);

-- One running (or paused) job per person. An index rather than a check in
-- code, so two Starts pressed at once cannot both pass a read and both run.
CREATE UNIQUE INDEX IF NOT EXISTS agent_job_one_running
    ON tasks.agent_job (user_email) WHERE status IN ('running','needs_you');

CREATE TABLE IF NOT EXISTS tasks.agent_job_step (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL REFERENCES tasks.agent_job(id) ON DELETE CASCADE,
    position   INT  NOT NULL,
    agent_id   TEXT NOT NULL,
    task       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'waiting'
               CHECK (status IN ('waiting','running','done','failed','skipped')),
    -- Counted when a step is claimed, kept when it is requeued: the retry
    -- limit reads it, and a restart mid-step counts as the attempt it was.
    attempts   INT  NOT NULL DEFAULT 0,
    result     TEXT,
    -- The tasks.agent_run row of the turn that produced the result.
    run_id     TEXT,
    UNIQUE (job_id, position)
);
