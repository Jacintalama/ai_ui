-- 052: what an agent actually did, and who asked it to.
--
-- agent_run says an agent ran, for how long, on which model and at what
-- cost. It has never said what the agent DID. agent_runner handles
-- tool_calls in memory and persists none of it, so the office can say
-- "working" and nothing more.
--
-- A handoff between agents is a tool call, so one table records both what an
-- agent is doing and who it is collaborating with.
--
-- No prose is stored. Not the question, not the answer. The tool's name is
-- the useful part: search_drive is "searching Drive". Storing what was asked
-- would be a privacy cost with no payoff, and it sits badly beside the
-- private agent conversations added on 2026-09-25.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.

CREATE TABLE IF NOT EXISTS tasks.agent_step (
    id              UUID        PRIMARY KEY,
    run_id          UUID        NOT NULL,
    agent_id        TEXT        NOT NULL,
    user_email      TEXT        NOT NULL,
    tool            TEXT        NOT NULL,
    -- Set only when the tool was a handoff. NULL for every other tool.
    target_agent_id TEXT,
    status          TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- "What did this run do", which is how a run is read back.
CREATE INDEX IF NOT EXISTS agent_step_run_idx
    ON tasks.agent_step (run_id);

-- "What has this person's office been doing lately", which is how the
-- activity surfaces read it.
CREATE INDEX IF NOT EXISTS agent_step_owner_recent_idx
    ON tasks.agent_step (user_email, started_at DESC);

-- Which run asked for this one. NULL for a run nobody asked for, which is
-- every run that exists today.
ALTER TABLE tasks.agent_run
    ADD COLUMN IF NOT EXISTS parent_run_id UUID;

CREATE INDEX IF NOT EXISTS agent_run_parent_idx
    ON tasks.agent_run (parent_run_id)
    WHERE parent_run_id IS NOT NULL;
