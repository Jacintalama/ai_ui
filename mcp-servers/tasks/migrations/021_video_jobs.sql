-- Migration 021: Add tasks.video_jobs — AI video generator render jobs.
--
-- One row per image+prompt -> narrated MP4 render job. The in-process video
-- worker in the tasks service polls for 'queued' rows and advances them
-- through scripting -> voicing -> rendering -> done/failed.
-- See docs/superpowers/plans/2026-06-15-ai-video-generator.md (Task 1.1).

CREATE TABLE IF NOT EXISTS tasks.video_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug          TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','scripting','voicing','rendering','done','failed')),
    prompt        TEXT NOT NULL,
    plan_json     JSONB,
    error         TEXT,
    output_path   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS video_jobs_status_idx ON tasks.video_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS video_jobs_user_idx   ON tasks.video_jobs (user_email, created_at DESC);

DROP TRIGGER IF EXISTS video_jobs_touch_updated_at ON tasks.video_jobs;
CREATE TRIGGER video_jobs_touch_updated_at BEFORE UPDATE ON tasks.video_jobs
    FOR EACH ROW EXECUTE FUNCTION tasks._touch_updated_at();
