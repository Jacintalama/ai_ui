-- 027_video_render_mode.sql  (idempotent; db.py re-runs every migration each startup)
ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS render_mode TEXT NOT NULL DEFAULT 'slideshow';
