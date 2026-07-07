-- 030: dedicated schedule kinds. 'agent' = existing prompt/executor runs
-- (all current rows); 'video' = direct video render of video_config.
-- Idempotent: db.py re-runs every migration each startup.
ALTER TABLE tasks.schedules
  ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'agent',
  ADD COLUMN IF NOT EXISTS video_config JSONB;
ALTER TABLE tasks.schedules DROP CONSTRAINT IF EXISTS schedules_kind_check;
ALTER TABLE tasks.schedules
  ADD CONSTRAINT schedules_kind_check CHECK (kind IN ('agent', 'video'));
