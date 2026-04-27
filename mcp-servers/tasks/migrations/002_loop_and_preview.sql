-- Loop mode columns
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS max_attempts    INT NOT NULL DEFAULT 1;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS attempt_count   INT NOT NULL DEFAULT 0;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS conversation_history JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS plan            TEXT;
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS plan_status     TEXT CHECK (plan_status IN ('pending_review','approved','rejected'));
ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS built_app_slug  TEXT;

-- Expand the status CHECK to include new states
ALTER TABLE tasks.items DROP CONSTRAINT IF EXISTS items_status_check;
ALTER TABLE tasks.items ADD CONSTRAINT items_status_check
    CHECK (status IN ('pending','planning','awaiting_plan_review','awaiting_supabase','claimed_manual','running','awaiting_input','completed','failed'));
