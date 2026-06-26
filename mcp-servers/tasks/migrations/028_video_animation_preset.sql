-- 028_video_animation_preset.sql  (idempotent; db.py re-runs every migration each startup)
ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS animation_preset TEXT NOT NULL DEFAULT 'cursor_click';

ALTER TABLE tasks.video_jobs
  ALTER COLUMN animation_preset SET DEFAULT 'cursor_click';

ALTER TABLE tasks.video_jobs
  ALTER COLUMN render_mode SET DEFAULT 'remotion';

UPDATE tasks.video_jobs
   SET animation_preset = 'cursor_click'
 WHERE animation_preset IS NULL OR animation_preset = '';

ALTER TABLE tasks.video_jobs
  DROP CONSTRAINT IF EXISTS video_jobs_animation_preset_check;

ALTER TABLE tasks.video_jobs
  ADD CONSTRAINT video_jobs_animation_preset_check
  CHECK (animation_preset IN ('cursor_click', 'smooth_scroll', 'spotlight', 'zoom_pan'));
