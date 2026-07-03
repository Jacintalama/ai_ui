-- Generic per-key state store for the chat bots (webhook-handler), so pending
-- intents / clarify replies / "current app" survive a redeploy instead of living
-- only in the webhook-handler process memory. Written/read via the system
-- /state endpoints (X-Internal-Secret). Idempotent.
CREATE TABLE IF NOT EXISTS tasks.bot_state (
    state_key  text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NULL
);
CREATE INDEX IF NOT EXISTS ix_bot_state_expires ON tasks.bot_state (expires_at);
