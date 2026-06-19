-- 025_video_collecting_status.sql
-- Add a 'collecting' draft status to tasks.video_jobs so the Discord video
-- wizard can accumulate title/prompt/style/voice/screenshots before the render
-- worker (which only picks 'queued') sees the job.
-- Idempotent: db.py re-runs every migration on each startup. We drop whatever
-- CHECK currently governs `status` (the implicitly-named 021 one OR our re-added
-- named one) and re-add the named superset, so repeated runs converge.
DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname
      FROM pg_constraint
     WHERE conrelid = 'tasks.video_jobs'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%status%'
     ORDER BY oid
     LIMIT 1;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE tasks.video_jobs DROP CONSTRAINT %I', cname);
    END IF;
    ALTER TABLE tasks.video_jobs
        ADD CONSTRAINT video_jobs_status_check
        CHECK (status IN ('queued','collecting','scripting','voicing','rendering','done','failed'));
END $$;
