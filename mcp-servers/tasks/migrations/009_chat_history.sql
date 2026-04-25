-- Per-(slug, user_email) chat history. Each row = one message. Order by created_at ASC.
-- We never auto-clear; only an explicit DELETE wipes a user's chat for a project.

CREATE TABLE IF NOT EXISTS tasks.chat_history (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL,
    user_email   TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chat_history_lookup_idx
    ON tasks.chat_history (slug, user_email, created_at);
