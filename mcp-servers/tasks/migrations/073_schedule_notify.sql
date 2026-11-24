-- 073: a cron can be muted, so its outputs do not ring the red number (2026-11-24).
--
-- The red number on Cron Jobs in the sidebar counts unread cron outputs
-- (072). A cron whose answers are nice to read but never need anything, a
-- daily quote for example, can be muted: its outputs still land in the Cron
-- Outputs inbox, but they arrive read and never count. See cron_quiet.py.
--
-- DEFAULT true, so every existing cron keeps counting exactly as before.
-- Idempotent, because db.py re-runs every migration on every startup.
ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS notify BOOLEAN NOT NULL DEFAULT true;
