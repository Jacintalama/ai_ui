-- 026_discord_link_video_thread.sql
-- Per-user private Discord thread for the video studio (created/reused by the
-- bot), separate from schedules_thread_id and builder_thread_id.
-- Idempotent: re-applied on every startup.
ALTER TABLE tasks.discord_links
    ADD COLUMN IF NOT EXISTS video_thread_id text;
