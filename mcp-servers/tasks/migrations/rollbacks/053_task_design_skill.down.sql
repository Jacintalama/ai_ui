-- Undo 053 by hand. Never placed in migrations/ itself: the startup runner
-- would run it on every boot (see tests/test_migrations_runner.py).
ALTER TABLE tasks.items DROP COLUMN IF EXISTS design_skill;
