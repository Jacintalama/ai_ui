-- 071: every run of a schedule, not just the most recent one.
--
-- tasks.schedules keeps last_run_status, last_result and last_result_at:
-- three columns describing the LAST run. Run a schedule a hundred times and
-- ninety-nine of those runs left no trace. So nothing could answer "has this
-- been failing all week", a card could show one mark rather than seven, and
-- there was nothing to alert on, because an alert has to know this failure is
-- the third in a row rather than the first.
--
-- WHY NOT tasks.agent_run, which has recorded one row per run since 044. Two
-- reasons, and the second is the deciding one. It carries no schedule id, so a
-- run cannot be attributed to the schedule that started it. And it is opened
-- in agent_runner.run_agent, which a VIDEO schedule and a schedule with NO
-- AGENT never reach -- and the kind with no agent is the kind that fails most
-- often, so a history that skipped it would be missing exactly the runs
-- somebody goes looking for.
--
-- The row is written in scheduler._finalize_run, which is the one funnel every
-- kind of run passes through, on both the success path and the exception path.
--
-- UNLIKE agent_run, THIS ONE CASCADES. 044 deliberately took no foreign key,
-- because Open WebUI owns public.model and an agent can be deleted at any
-- moment, so losing an agent's history the instant it is deleted would be
-- worse than keeping rows that point at nothing. tasks.schedules is ours,
-- nothing reads the history of a schedule that no longer exists, and without
-- the cascade those rows would accumulate for ever with no reader.
--
-- `result` is written through scheduler.result_for_storage, the same scrubbing
-- and the same cap as last_result: agent output can repeat a credential it was
-- handed, and this lands in a row and then on a page.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.schedule_run (
    id          UUID        PRIMARY KEY,
    schedule_id UUID        NOT NULL
                REFERENCES tasks.schedules (id) ON DELETE CASCADE,
    user_email  TEXT        NOT NULL DEFAULT '',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT,
    result      TEXT
);

-- The only question anybody asks of this table: "the last seven runs of this
-- schedule, newest first". Without the ordering in the index that is a sort
-- of every run ever recorded.
CREATE INDEX IF NOT EXISTS schedule_run_recent_idx
    ON tasks.schedule_run (schedule_id, started_at DESC);
