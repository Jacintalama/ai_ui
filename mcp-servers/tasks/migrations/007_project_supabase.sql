-- Per-project Supabase config. anon_key_encrypted holds a Fernet ciphertext;
-- decrypt only at request time. We never accept service-role keys — clients
-- should configure their app with anon + Row Level Security policies.

CREATE TABLE IF NOT EXISTS tasks.project_supabase (
    slug                TEXT PRIMARY KEY,
    supabase_url        TEXT NOT NULL,
    anon_key_encrypted  TEXT NOT NULL,
    configured_by       TEXT NOT NULL,
    configured_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
