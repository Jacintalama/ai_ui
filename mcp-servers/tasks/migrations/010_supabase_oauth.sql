-- Supabase OAuth integration. When a user "Connects Supabase" via OAuth,
-- we store the access + refresh tokens encrypted and remember which of
-- their Supabase projects they linked.

ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS oauth_access_token_encrypted TEXT;
ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS oauth_refresh_token_encrypted TEXT;
ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS oauth_expires_at TIMESTAMPTZ;
ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS linked_project_ref TEXT;
ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS oauth_org_slug TEXT;

-- Allow rows that were created BY OAuth (no manual URL/key initially) — relax NOT NULL.
ALTER TABLE tasks.project_supabase ALTER COLUMN supabase_url DROP NOT NULL;
ALTER TABLE tasks.project_supabase ALTER COLUMN anon_key_encrypted DROP NOT NULL;
