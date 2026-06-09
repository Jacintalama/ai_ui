-- 020: one-time schedules. NULL/false = repeating (existing behavior).
ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS run_once BOOLEAN NOT NULL DEFAULT FALSE;
