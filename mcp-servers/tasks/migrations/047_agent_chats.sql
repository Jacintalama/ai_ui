-- 047: saved conversations for the agent chat panel on the AI Agents page.
--
-- Its own table, deliberately nothing to do with Open WebUI's chat. Borrowing
-- that chat is what the previous attempt did, and it failed because Open WebUI
-- renders message.output rather than message.content. The panel draws its own
-- messages, so it needs its own store.
--
-- messages/room/pending are JSONB because a conversation is only ever read and
-- written as a unit, the same reasoning as 032_fusion_chats.
--
-- `pending` holds an approval question nobody has answered yet, keyed by agent
-- id, so a service restart does not turn a waiting Yes/No into a dead button.
--
-- Idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.agent_chats (
  id         TEXT PRIMARY KEY,
  user_email TEXT NOT NULL,
  title      TEXT NOT NULL DEFAULT 'New chat',
  messages   JSONB NOT NULL DEFAULT '[]'::jsonb,
  room       JSONB NOT NULL DEFAULT '[]'::jsonb,
  pending    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The panel's only list query: this person's conversations, newest first.
CREATE INDEX IF NOT EXISTS agent_chats_user_updated
  ON tasks.agent_chats (user_email, updated_at DESC);
