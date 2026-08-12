-- 035: remember which platform account a link belongs to.
--
-- Redeeming a code grants a chat account full access to the redeemer's memory,
-- Gmail assistant and Documents. Without a name stored on the link, the UI can
-- only say "Telegram connected" and never "connected to @someone", so a user
-- who was talked into pasting a code they were sent has no way to see whose
-- account is now reading their Brain. The name is already collected on the
-- pairing code; this carries it across to the link that outlives it.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.gateway_links
    ADD COLUMN IF NOT EXISTS platform_user_name TEXT;
