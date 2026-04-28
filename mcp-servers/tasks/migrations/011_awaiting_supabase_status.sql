-- Add 'awaiting_supabase' to the items.status CHECK constraint.
-- A BUILD task whose template requires Supabase but has no Supabase row yet
-- enters this status and waits for the user to connect (or skip) before
-- transitioning to 'pending' and kicking off the build.

ALTER TABLE tasks.items DROP CONSTRAINT IF EXISTS items_status_check;
ALTER TABLE tasks.items ADD CONSTRAINT items_status_check
    CHECK (status = ANY (ARRAY[
        'pending'::text,
        'planning'::text,
        'awaiting_plan_review'::text,
        'awaiting_supabase'::text,
        'claimed_manual'::text,
        'running'::text,
        'awaiting_input'::text,
        'completed'::text,
        'failed'::text
    ]));
