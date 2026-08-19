-- 039: per-user credentials for third-party tools.
--
-- The Connections dialog listed sixteen apps and could connect one. Four of
-- the greyed-out cards (ClickUp, GitHub, Trello, n8n) already had a running
-- container and an indexed tool list. The missing piece was never the route to
-- the vendor, it was anywhere to put the USER's credential: those containers
-- take one token from boot-time env, so every call acts as the platform
-- account.
--
-- secrets_encrypted holds a Fernet-encrypted JSON object rather than a single
-- column, because providers do not agree on how many pieces a credential has.
-- Trello signs with an API key AND a token, n8n needs a self-hosted base URL
-- AND an api key, ClickUp needs one string. A column per field would mean a
-- migration per provider.
--
-- The value is encrypted by crypto_utils (AIUI_FERNET_KEY) BEFORE it reaches
-- this table, the same way tasks.gateway_bots stores bot tokens. Nothing here
-- is ever returned to a client.
--
-- account_label is the name the vendor gave back when the credential was
-- checked. It is stored so a card can say WHICH account is connected without
-- decrypting anything or calling the vendor on every page load.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.user_connections (
    email             TEXT        NOT NULL,
    provider          TEXT        NOT NULL,
    secrets_encrypted TEXT        NOT NULL,
    account_label     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (email, provider)
);

CREATE INDEX IF NOT EXISTS user_connections_email_idx
    ON tasks.user_connections (email);
