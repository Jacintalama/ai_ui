-- Schedules can deliver each run's result into a Discord channel/thread.
-- Idempotent: re-applied on every startup (init_db runs all migrations/*.sql).
ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS delivery_channel_id text;
