-- Per-user private Discord thread for schedules (created/reused by the bot).
-- Idempotent: re-applied on every startup (init_db runs all migrations/*.sql).
ALTER TABLE tasks.discord_links
    ADD COLUMN IF NOT EXISTS schedules_thread_id text;
