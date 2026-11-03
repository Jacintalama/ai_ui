-- 065: A card on a Trello list can start an automation
-- (trello_trigger.py, trello_poller.py).
--
-- Migration 064 added the email trigger and the `trigger_query` column with
-- it. This trigger needs no new column on `automation`: `trigger` takes a
-- new value, and `trigger_query` holds the Trello LIST ID instead of a
-- Gmail search. One column, two meanings, decided by the trigger beside it.
--
-- That reuse is deliberate and is the smaller of two evils. The other way
-- is a column per trigger kind, every one of them null for every rule but
-- its own, and a third trigger makes it three. What keeps it honest is that
-- nothing reads `trigger_query` without first reading `trigger`:
-- automations.problem_with dispatches on the kind, and each poller selects
-- `WHERE trigger = :kind`.
--
-- The cursor gets its own table rather than joining the email one. They
-- hold different things and are written by different pollers: the email
-- cursor's `seen_ids` are message ids, where these marks are `cardid@epoch`
-- (see trello_trigger.mark). A card is not an email. An email arrives once
-- and its id is enough to know it was handled; a card keeps changing, so
-- remembering the id alone would fire once and then stay silent however
-- much happened to it afterwards.
--
-- `after_epoch` is seconds, from Trello's own `dateLastActivity`, never
-- from a due date: a due date is set by whoever made the card and says
-- nothing about when it changed.
--
-- It is set to the moment the rule is created and NEVER to zero. Unlike
-- Gmail, Trello does no filtering for us: the cards call returns every card
-- on the list whatever its age, so a rule starting at zero fires on all of
-- them, and this trigger runs one agent turn per card.
--
-- Additive and idempotent: db.py re-runs every migration on each startup,
-- so a failure here would block every later one.

CREATE TABLE IF NOT EXISTS tasks.automation_trello_cursor (
    automation_id  UUID PRIMARY KEY,
    user_email     TEXT NOT NULL,
    -- Trello dateLastActivity seconds. The rule's creation time at first.
    after_epoch    BIGINT NOT NULL,
    -- Newest first, comma separated, each one `cardid@epoch`. Capped by
    -- trello_trigger.SEEN_KEPT.
    seen_marks     TEXT NOT NULL DEFAULT '',
    checked_at     TIMESTAMPTZ,
    -- Why the last look did not work, shown on the page so a rule that has
    -- quietly stopped looking is visible rather than merely silent.
    last_error     TEXT NOT NULL DEFAULT ''
);

-- The poller walks every rule that is due, so it reads by owner.
CREATE INDEX IF NOT EXISTS automation_trello_cursor_owner
    ON tasks.automation_trello_cursor (user_email);
