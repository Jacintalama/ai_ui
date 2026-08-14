-- Buzz needs two things gateway_bots did not carry, because Buzz is the first
-- channel IO connects OUT to rather than one that calls us.
--
--   endpoint      where to connect. Telegram's address is Telegram's; a Buzz
--                 relay belongs to the user, so it has to be stored per row.
--   connected_at  whether it actually worked. Only the process holding the
--                 socket can know, so webhook-handler writes this through the
--                 internal state endpoint. NULL for Telegram, which holds
--                 nothing open and reports failure by not calling us.
--
-- Idempotent: safe to run again.
ALTER TABLE tasks.gateway_bots
  ADD COLUMN IF NOT EXISTS endpoint text NOT NULL DEFAULT '';
ALTER TABLE tasks.gateway_bots
  ADD COLUMN IF NOT EXISTS connected_at timestamptz;
