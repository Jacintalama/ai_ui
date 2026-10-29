-- 064: An email can start an automation (email_trigger.py, email_poller.py).
--
-- Migration 060 left `trigger TEXT NOT NULL DEFAULT 'webhook'` with the
-- comment "an email trigger comes next and will add a trigger kind here".
-- This is that. The trigger column needs no change, only new values in it.
--
-- Two additions:
--
--   automation.trigger_query  the Gmail search that decides which emails
--                             start this rule ("from:boss@x.com is:unread").
--                             Matching is Gmail's job, not ours: a local
--                             reimplementation of from/subject/label would
--                             be a worse version of something it already
--                             does well, and would drift from it.
--
--   automation_email_cursor   how far through the mailbox each rule has
--                             got. One row per RULE, not per account,
--                             because each rule has its own query and so
--                             its own idea of what it has already seen.
--
-- `after_epoch` is seconds, from Gmail's own internalDate, never from the
-- Date header (the sender writes that one and it is routinely wrong,
-- absent, or in a format nobody agreed on).
--
-- It is set to the moment the rule is created and NEVER to zero. A rule
-- starting at zero fires on every email in the mailbox's history, and this
-- trigger runs one agent turn per message, so that is a bill and an inbox
-- full of replies rather than a feature.
--
-- `seen_ids` is the recently fired message ids, newest first, because the
-- poller queries with a deliberate overlap (Gmail's `after:` is inclusive
-- and uses its clock, not ours) and must drop what it has already acted on.
-- Stored as text rather than an array to keep this readable from psql and
-- to avoid an array type in a table nothing joins on.
--
-- Additive and idempotent: db.py re-runs every migration on each startup,
-- so a failure here would block every later one.

ALTER TABLE tasks.automation
    ADD COLUMN IF NOT EXISTS trigger_query TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS tasks.automation_email_cursor (
    automation_id  UUID PRIMARY KEY,
    user_email     TEXT NOT NULL,
    -- Gmail internalDate seconds. The rule's creation time at first.
    after_epoch    BIGINT NOT NULL,
    -- Newest first, comma separated. Capped by email_trigger.SEEN_KEPT.
    seen_ids       TEXT NOT NULL DEFAULT '',
    checked_at     TIMESTAMPTZ,
    -- Why the last check did not work, shown on the page so a rule that
    -- has quietly stopped looking is visible rather than merely silent.
    last_error     TEXT NOT NULL DEFAULT ''
);

-- The poller walks every rule that is due, so it reads by owner and age.
CREATE INDEX IF NOT EXISTS automation_email_cursor_owner
    ON tasks.automation_email_cursor (user_email);
