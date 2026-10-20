-- Undo 057 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
DROP TABLE IF EXISTS tasks.agent_decision;
