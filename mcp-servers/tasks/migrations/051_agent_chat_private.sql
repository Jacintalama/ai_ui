-- 051: a conversation can belong to one agent instead of to the room.
--
-- Until now there was exactly one conversation per person and everybody heard
-- everything. Naming an agent routed the answer to them, but the question and
-- the reply still sat in the shared room where every other agent read them as
-- context. There was nowhere to put a private word with one agent.
--
-- NULL means the room, which is what every existing row is and what the panel
-- opens on. A value is that agent's own conversation with this person.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
ALTER TABLE tasks.agent_chats
  ADD COLUMN IF NOT EXISTS agent_id TEXT;

-- One conversation per person per agent, and one room per person. A partial
-- index for each, because NULL is not equal to itself: a plain unique index
-- over (user_email, agent_id) would let a person collect any number of rooms.
CREATE UNIQUE INDEX IF NOT EXISTS agent_chats_one_private
  ON tasks.agent_chats (user_email, agent_id)
  WHERE agent_id IS NOT NULL;

-- Not unique for the room. 047 never promised it and production may already
-- hold more than one; newest_chat orders by updated_at and takes the one
-- still being used, which is the behaviour that shipped.
CREATE INDEX IF NOT EXISTS agent_chats_user_room
  ON tasks.agent_chats (user_email, updated_at DESC)
  WHERE agent_id IS NULL;
