-- Undo 050 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
DROP INDEX IF EXISTS tasks.agent_run_paid_today_idx;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS cost_usd;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS completion_tokens;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS prompt_tokens;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS escalation;
ALTER TABLE tasks.agent_run DROP COLUMN IF EXISTS model;
