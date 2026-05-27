-- Self-service Discord↔email links (admin-approved). One row per Discord user.
-- Idempotent: re-applied on every startup (init_db runs all migrations/*.sql).
CREATE TABLE IF NOT EXISTS tasks.discord_links (
    discord_id        text PRIMARY KEY,
    discord_username  text,
    email             text NOT NULL,
    status            text NOT NULL DEFAULT 'pending',
    requested_at      timestamptz DEFAULT now(),
    decided_at        timestamptz,
    decided_by        text
);
