-- Optional Postgres connection URI for AI-managed schema setup.
-- Encrypted at rest with the same Fernet key as anon_key_encrypted.
ALTER TABLE tasks.project_supabase
    ADD COLUMN IF NOT EXISTS db_uri_encrypted TEXT;
