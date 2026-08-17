-- 037: a second encrypted credential, for channels that need two.
--
-- Slack Socket Mode needs BOTH:
--   xoxb-  the bot token, which sends messages
--   xapp-  the app-level token, which opens the websocket
-- They are issued separately, fail separately, and are both secrets, so the
-- second cannot ride in `endpoint` (which is not encrypted and comes back to
-- the browser) and must not be packed into `token_encrypted` as a private
-- format only one platform's code knows how to read.
--
-- NULL for every channel that needs one credential, which is all of them
-- except Slack.
--
-- Idempotent: db.py re-runs every migration on every startup, so this uses
-- IF NOT EXISTS and never drops anything. A migration that drops and re-adds
-- a column on each boot is what once consumed 1593 column slots on
-- tasks.executions and stopped the service booting at all -- see
-- db.py::migration_files.

ALTER TABLE tasks.gateway_bots
    ADD COLUMN IF NOT EXISTS app_token_encrypted TEXT;
