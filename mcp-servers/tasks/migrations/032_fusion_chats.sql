-- 032: saved Fusion conversations, so the page can show a chat history in its
-- sidebar the way Open WebUI does. Before this, sessions lived only in memory
-- and were lost on New chat or on a service restart.
--
-- messages/panel are JSONB: a Fusion turn is a whole conversation snapshot that
-- is only ever read and written as a unit, so there is nothing to gain from a
-- separate per-message table.
-- Idempotent: db.py re-runs every migration each startup.
CREATE TABLE IF NOT EXISTS tasks.fusion_chats (
  id           TEXT PRIMARY KEY,
  user_email   TEXT NOT NULL,
  title        TEXT NOT NULL DEFAULT 'New chat',
  messages     JSONB NOT NULL DEFAULT '[]'::jsonb,
  panel        JSONB NOT NULL DEFAULT '[]'::jsonb,
  judge        TEXT,
  preset_label TEXT NOT NULL DEFAULT 'quality',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The sidebar's only query: this user's chats, newest first.
CREATE INDEX IF NOT EXISTS fusion_chats_user_updated
  ON tasks.fusion_chats (user_email, updated_at DESC);
