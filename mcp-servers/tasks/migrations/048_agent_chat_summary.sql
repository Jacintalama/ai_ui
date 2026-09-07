-- 048: notes standing in for the turns that no longer fit an agent's budget.
--
-- The agent chat panel is one permanent room rather than a list of separate
-- conversations, so it grows forever. Sending all of it to every agent on
-- every message would cost several times itself on a 3.8GB box, and dropping
-- the oldest turns would mean an agent forgetting what was agreed this
-- morning. So the oldest part is folded into notes and those ride in front of
-- the recent turns instead.
--
-- Additive. The `room` column from 047 stays where it is: the panel no longer
-- writes it, and dropping a column is not worth the risk for the few bytes.
-- Idempotent: db.py re-runs every migration on each startup.
ALTER TABLE tasks.agent_chats
  ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
