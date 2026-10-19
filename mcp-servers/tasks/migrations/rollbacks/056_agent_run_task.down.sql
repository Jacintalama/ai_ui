-- Undo 056 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
DROP INDEX IF EXISTS tasks.agent_run_task_idx;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS task_id;
