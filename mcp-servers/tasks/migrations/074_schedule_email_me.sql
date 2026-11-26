-- 074: a cron job can email its answer to the person who owns it (2026-11-26).
--
-- Measured: the only cron runs that failed in two weeks were jobs asked to
-- email their summary. A schedule runs read only unless its agent may act on
-- its own everywhere, so "email me a summary" was refused every time.
-- Emailing yourself the answer is delivery, done by the platform through the
-- person's own connected Gmail after the run (cron_email.py), so the agent
-- stays read only.
--
-- DEFAULT false, so every existing cron delivers exactly as before.
-- Idempotent, because db.py re-runs every migration on every startup.
ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS email_me BOOLEAN NOT NULL DEFAULT false;
