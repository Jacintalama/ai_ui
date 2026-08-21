-- 040: keep what a scheduled run produced.
--
-- scheduler.py delivered a run's result to Discord or Slack and, when there
-- was no destination, dropped it:
--
--     if delivery_channel:
--         await _deliver_result(...)
--
-- The row still recorded last_run_status='completed', so the card said
-- "Completed" and the user received nothing, having spent a real agent run to
-- produce it. Every schedule created from the web page is in that state,
-- because that form has never had a destination to set.
--
-- Storing the result fixes it at the root: a schedule is useful with no
-- Discord and no Slack at all, and delivery becomes a way to ALSO push the
-- answer somewhere rather than the only way to ever see it.
--
-- The value is scrubbed and length-capped before it gets here
-- (scheduler.result_for_storage), because agent output can repeat a credential
-- it was handed and is otherwise unbounded.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS last_result TEXT;

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS last_result_at TIMESTAMPTZ;
