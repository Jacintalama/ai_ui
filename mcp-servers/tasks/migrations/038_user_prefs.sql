-- 038: per-user preferences, starting with the timezone.
--
-- Every model on the platform answered date and time questions with nothing to
-- go on: no date, no time, no zone. The browser already knows the answer, as an
-- IANA zone name, so it can be learned without asking anyone.
--
-- The stored value is an IANA name and never a UTC offset. An offset is right
-- for half the year in any zone that observes daylight saving, and it fails
-- silently: a schedule set in March fires an hour off in April.
--
-- tz_source exists because autodetect runs on every page load. Without it, a
-- user who sets their zone by hand loses it the moment they open the app from
-- a laptop in another zone.
--
-- A general prefs table rather than a user_timezone table, so the next
-- per-user preference does not need another migration.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.user_prefs (
    email       TEXT PRIMARY KEY,
    timezone    TEXT,
    tz_source   TEXT NOT NULL DEFAULT 'auto',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
