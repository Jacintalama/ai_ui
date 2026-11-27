-- 075: a person's own MCP servers (2026-11-27).
--
-- A person pastes the address of an MCP server they run (or a vendor hosts)
-- and an optional token in Connections. Its tools become tools for that
-- person only, named own-<slug>_<tool> (own_mcp.py).
--
-- The address is stored INSIDE the encrypted blob with the token, because
-- some vendors put the key in the address; `host` is all a card shows.
-- `tools` is the snapshot from the last successful listing. `fails` counts
-- failed checks in a row; at 3, check_ok goes false and the card says the
-- server is not answering (the tools stay listed).
--
-- A table of its own rather than tasks.user_connections: that one is keyed
-- by a provider id from the built catalogue, and every route reading it
-- assumes so.
--
-- Idempotent, because db.py re-runs every migration on every startup.
CREATE TABLE IF NOT EXISTS tasks.own_mcp_servers (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email             TEXT        NOT NULL,
    slug              TEXT        NOT NULL,
    label             TEXT        NOT NULL,
    host              TEXT        NOT NULL,
    secrets_encrypted TEXT        NOT NULL,
    tools             JSONB       NOT NULL DEFAULT '[]',
    check_ok          BOOLEAN     NOT NULL DEFAULT TRUE,
    fails             INT         NOT NULL DEFAULT 0,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (email, slug)
);
CREATE INDEX IF NOT EXISTS own_mcp_servers_email_idx
    ON tasks.own_mcp_servers (email);
