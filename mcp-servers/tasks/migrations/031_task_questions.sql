-- 031: pre-build clarifying questions (structured, capped at 3, one round).
-- Separate from the free-text mid-build NEEDS_INPUT mechanism (item.result);
-- questions_json is only ever populated by the new pre-build question pass.
-- Idempotent: db.py re-runs every migration each startup.
ALTER TABLE tasks.items
  ADD COLUMN IF NOT EXISTS questions_json JSONB,
  ADD COLUMN IF NOT EXISTS questions_asked_at TIMESTAMPTZ;
