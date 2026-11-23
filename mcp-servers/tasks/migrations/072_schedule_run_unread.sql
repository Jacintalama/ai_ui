-- 072: a cron output is read or unread, like an email (2026-11-23).
--
-- The Cron Outputs page (/cronjobs/output) is an inbox: a run's answer
-- arrives unread, opening it marks it read, and the red count on Cron Jobs in
-- the sidebar is how many are still unread. That state lives here, on the
-- server, so it is the same on every device and in every tab, which a count
-- kept in one browser's localStorage could never be.
--
-- DEFAULT false, so every run recorded BEFORE this column existed reads as
-- already read: nobody opens the page to thirty unread outputs from last
-- week. A NEW run is written unread by scheduler._record_run, explicitly.
--
-- Idempotent, because db.py re-runs every migration on every startup. That
-- is also why there is no UPDATE here: one would mark everything read again
-- on every restart.
ALTER TABLE tasks.schedule_run
    ADD COLUMN IF NOT EXISTS unread BOOLEAN NOT NULL DEFAULT false;

-- The question asked every 30 seconds by every open tab: how many unread.
-- Partial, so it holds only the few rows that are unread.
CREATE INDEX IF NOT EXISTS schedule_run_unread_idx
    ON tasks.schedule_run (schedule_id)
    WHERE unread;
