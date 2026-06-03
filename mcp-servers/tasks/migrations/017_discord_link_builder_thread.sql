-- Per-user private Discord thread for the App Builder (created/reused by the bot).
-- Separate from schedules_thread_id so the builder gets its own thread.
-- Idempotent: re-applied on every startup (init_db runs all migrations/*.sql).
ALTER TABLE tasks.discord_links
    ADD COLUMN IF NOT EXISTS builder_thread_id text;
