-- 067: a build says which step it is on (build_progress.py).
--
-- The main chat already watches a build and already draws a live line
-- under the reply, and until now that line could only count minutes:
--
--     Still building, 4 min so far.
--
-- A timer is not progress. It says the thing is alive and nothing about
-- whether it is nearly done, stuck on a browser check, or rolling back.
-- The build knows all of that: _run_execution runs named steps in order
-- and has since it was written. Nothing carried the name out of the
-- process.
--
-- One nullable column, because the page already polls this row every few
-- seconds. A second table would be a second query on that same poll for a
-- single short string, and a push channel would be a new delivery path to
-- get right for something the page is already asking for.
--
-- NULL means a build that predates this, or one between steps. The line
-- falls back to counting minutes, which is what it did before.
--
-- Additive and idempotent: db.py re-runs every migration on each startup,
-- so a failure here would block every later one.

ALTER TABLE tasks.items
    ADD COLUMN IF NOT EXISTS build_step TEXT;

-- When the step was set, so a step that has not moved in a long while is
-- distinguishable from one that is simply slow. Written by the same update
-- as the step itself.
ALTER TABLE tasks.items
    ADD COLUMN IF NOT EXISTS build_step_at TIMESTAMPTZ;
