-- Undo 058 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
DROP TABLE IF EXISTS tasks.jev_check;
ALTER TABLE tasks.agent_decision DROP COLUMN IF EXISTS urgency_confidence;
ALTER TABLE tasks.agent_decision DROP COLUMN IF EXISTS urgency;
