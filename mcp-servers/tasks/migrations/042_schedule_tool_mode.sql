-- 042: how much a scheduled agent is allowed to do.
--
-- 'read_only' lets the agent call tools that only read. 'full' lets it call
-- everything, including sending mail. NULL means read_only: every row that
-- exists today predates the tool loop and none of their owners has been
-- asked yet, so the quiet default has to be the safe one.
--
-- Deliberately not NOT NULL with a default. Backfilling would write a
-- decision nobody made onto every existing schedule, and NULL carries the
-- useful distinction between "chose read_only" and "was never asked".
--
-- 'ask' is intentionally absent. It needs a run that can suspend and resume
-- and a person to answer, which is Phase 2. A value the code cannot honour
-- would be worse than one that is not offered yet.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS tool_mode TEXT;
