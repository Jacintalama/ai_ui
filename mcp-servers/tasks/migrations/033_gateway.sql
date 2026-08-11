-- 033: multi-platform gateway. Three tables:
--   gateway_links          a platform account paired to an IO account
--   gateway_pairing_codes  short-lived codes that create those links
--   gateway_sessions       a platform conversation -> a real Open WebUI chat
--
-- webhook-handler has no database driver, so it reaches all three over HTTP
-- through routes_gateway.py. Nothing else reads them.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.gateway_links (
    id                BIGSERIAL PRIMARY KEY,
    platform          TEXT        NOT NULL,
    platform_user_id  TEXT        NOT NULL,
    owui_user_id      TEXT        NOT NULL,
    email             TEXT        NOT NULL,
    linked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One IO account per platform account. Without this, identity is ambiguous and
-- which one wins depends on row order.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_links_platform_user
    ON tasks.gateway_links (platform, platform_user_id);

CREATE TABLE IF NOT EXISTS tasks.gateway_pairing_codes (
    id                 BIGSERIAL PRIMARY KEY,
    -- sha256 of the code, never the code. A dump of this table grants nothing.
    code_hash          TEXT        NOT NULL,
    platform           TEXT        NOT NULL,
    platform_user_id   TEXT        NOT NULL,
    platform_user_name TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL,
    redeemed_at        TIMESTAMPTZ
);

-- Both hot paths: "does this platform user already have a live code" on every
-- unpaired message, and "find the row for this code" on redeem.
CREATE INDEX IF NOT EXISTS gateway_pairing_codes_platform_user
    ON tasks.gateway_pairing_codes (platform, platform_user_id);
CREATE INDEX IF NOT EXISTS gateway_pairing_codes_hash
    ON tasks.gateway_pairing_codes (code_hash);

CREATE TABLE IF NOT EXISTS tasks.gateway_sessions (
    id            BIGSERIAL PRIMARY KEY,
    platform      TEXT        NOT NULL,
    chat_id       TEXT        NOT NULL,
    -- The Open WebUI chat is the ONLY transcript. The gateway keeps no copy,
    -- so there is nothing that can drift out of sync with the user's sidebar.
    owui_chat_id  TEXT        NOT NULL,
    owui_user_id  TEXT        NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS gateway_sessions_platform_chat
    ON tasks.gateway_sessions (platform, chat_id);

-- /resume lists a user's recent gateway chats, newest first.
CREATE INDEX IF NOT EXISTS gateway_sessions_user_updated
    ON tasks.gateway_sessions (owui_user_id, updated_at DESC);
