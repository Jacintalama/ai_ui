-- 055: when the current attempt at a job step began.
--
-- A step is retried after a failure, and run again after a restart that cut
-- it off, but only if that attempt did not act: a step that already sent an
-- email must not send it twice. What it did is in tasks.agent_step, under the
-- run its turn opened, and that run started after the step was claimed. The
-- claim stamps this column, so "did this attempt run a tool" is a question
-- about runs of this agent, for this person, from a job, since then
-- (agent_job_store.step_acted). See agent_job_worker._failed.
--
-- NULL on steps claimed before this existed; the job's started_at stands in.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.

ALTER TABLE tasks.agent_job_step
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
