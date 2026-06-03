-- Idempotent: re-applied on every startup. Existing rows default to 'discord'
-- so all current Discord behavior is preserved.
ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS delivery_platform text DEFAULT 'discord';
