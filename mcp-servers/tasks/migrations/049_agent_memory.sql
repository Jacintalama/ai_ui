-- 049: what an agent remembers between conversations.
--
-- Nothing carried across a chat before this. The panel summarises one
-- conversation (048), a schedule gets its own last result, and the remember
-- tool writes to Open WebUI's public.memory table, which held 0 rows after a
-- year because nothing on the agent path read it back. This table is the
-- agent's own notes: what it did for this person, what is open, how they
-- like its output. Facts about the PERSON stay in public.memory so they show
-- in Settings > Personalization > Memories and the Brain graph.
--
-- `key` is the note normalised (lower case, punctuation stripped, whitespace
-- collapsed, 120 characters) and is what makes the same note said twice one
-- row. A reflection that re-learns a fact touches last_seen_at instead of
-- adding a duplicate.
--
-- No foreign key to public.model: Open WebUI owns that table and an agent
-- can be deleted at any moment, the same reasoning as 044.
--
-- Idempotent: db.py re-runs every migration on every startup.
CREATE TABLE IF NOT EXISTS tasks.agent_memory (
    id           UUID        PRIMARY KEY,
    agent_id     TEXT        NOT NULL,
    user_email   TEXT        NOT NULL,
    content      TEXT        NOT NULL,
    key          TEXT        NOT NULL,
    source       TEXT        NOT NULL DEFAULT 'reflection',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, user_email, key)
);

-- The recall query: this person's notes for this agent, newest first.
CREATE INDEX IF NOT EXISTS agent_memory_recall_idx
    ON tasks.agent_memory (user_email, agent_id, last_seen_at DESC);
