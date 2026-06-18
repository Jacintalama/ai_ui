-- 023_video_title.sql  (idempotent; db.py re-runs every migration each startup)
ALTER TABLE tasks.video_jobs ADD COLUMN IF NOT EXISTS title TEXT;
