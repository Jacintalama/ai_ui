-- 024_video_style_voice.sql  (idempotent; db.py re-runs every migration each startup)
ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS style TEXT NOT NULL DEFAULT 'clean_product_demo',
  ADD COLUMN IF NOT EXISTS voice TEXT;
