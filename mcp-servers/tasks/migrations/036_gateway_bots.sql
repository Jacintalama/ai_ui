-- 036: a user's own chat bot.
--
-- Hermes configures one bot per server. IO has many accounts, so a bot belongs
-- to exactly one of them: their token, their data, invisible to everyone else.
--
-- The token is Fernet-encrypted by the application before it ever reaches this
-- table, so a dump of this database grants nobody the ability to send as
-- anyone's bot.
--
-- bot_key is NOT a secret. It is the opaque path segment in
-- /webhook/telegram/{bot_key}. Authentication is webhook_secret, which Telegram
-- echoes back in the x-telegram-bot-api-secret-token header.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.gateway_bots (
    id                      BIGSERIAL PRIMARY KEY,
    bot_key                 TEXT        NOT NULL,
    email                   TEXT        NOT NULL,
    platform                TEXT        NOT NULL,
    token_encrypted         TEXT        NOT NULL,
    webhook_secret          TEXT        NOT NULL,
    bot_username            TEXT,
    -- Comma-separated platform user ids allowed to talk to this bot. Empty
    -- means owner only, enforced through owner_platform_user_id below.
    allowed_ids             TEXT        NOT NULL DEFAULT '',
    -- The platform account that claimed this bot by messaging it first. NULL
    -- until first contact. Claiming decides who the bot talks to; it does NOT
    -- link an IO account, which still requires a pairing code.
    owner_platform_user_id  TEXT,
    enabled                 BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error              TEXT
);

-- The inbound hot path: one lookup per update on a cold cache.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_bots_key
    ON tasks.gateway_bots (bot_key);

-- The Channels page lists this account's bots.
CREATE INDEX IF NOT EXISTS gateway_bots_email
    ON tasks.gateway_bots (email);

-- One bot per platform per account. A second Telegram bot for the same user
-- would make "which bot does IO start a conversation on" ambiguous.
CREATE UNIQUE INDEX IF NOT EXISTS gateway_bots_email_platform
    ON tasks.gateway_bots (email, platform);
