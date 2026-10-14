-- Undo 054 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
-- Drops every agent job and its steps.
DROP TABLE IF EXISTS tasks.agent_job_step;
DROP TABLE IF EXISTS tasks.agent_job;
