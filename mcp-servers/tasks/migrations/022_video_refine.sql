-- 022_video_refine.sql
-- Refine-chat support: version history + per-job conversation. Idempotent:
-- db.py re-runs every migration file on every startup, so use IF NOT EXISTS.

ALTER TABLE tasks.video_jobs
  ADD COLUMN IF NOT EXISTS conversation       JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS current_version_no INT,
  ADD COLUMN IF NOT EXISTS pending_summary    TEXT;

CREATE TABLE IF NOT EXISTS tasks.video_job_versions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES tasks.video_jobs(id) ON DELETE CASCADE,
  version_no  INT  NOT NULL,
  plan_json   JSONB NOT NULL,
  summary     TEXT,
  output_path TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (job_id, version_no)
);

CREATE INDEX IF NOT EXISTS video_job_versions_job_idx
  ON tasks.video_job_versions (job_id, version_no DESC);
