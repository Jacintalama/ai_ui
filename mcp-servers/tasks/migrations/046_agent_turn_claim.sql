-- 046: who already owns a given agent's turn in a given chat.
--
-- Numbered 046, not 045: 045_agent_turn_claim was the name in the review
-- dispatch, but 045_agent_proposals.sql already exists and the runner applies
-- every file on every startup in sorted order, so a duplicate number would be
-- ambiguous forever.
--
-- The web page takes turns by finding a hidden marker on the last reply and
-- calling /agents/speak for the next agent. The page claims a turn before
-- running it, by rewriting that marker, but a page cannot make a claim stick:
-- reading the chat and writing it back are two separate HTTP calls and the
-- Open WebUI chat endpoint is a blind overwrite with no If-Match, so two tabs
-- open on the same conversation both read the marker before either writes and
-- both run the agent. That was measured, not theorised.
--
-- The consequence is not a cosmetic duplicate. An agent's turn can send an
-- email or a calendar invite, and nobody can unsend one. So the decision about
-- who runs a turn has to be made somewhere that can be atomic, and the only
-- such place is here.
--
-- The primary key IS the whole argument. INSERT ... ON CONFLICT DO NOTHING
-- against these four columns is decided by Postgres under a unique index, so
-- exactly one caller can ever win, and no lock, no transaction level and no
-- application logic is needed to make that true.
--
-- after_id is the id of the message the turn answers: the tail the page
-- claimed against. It is part of the key because the same agent legitimately
-- speaks many times in one chat, just never twice for the same preceding
-- message.
--
-- A claim row is DELIBERATELY NEVER RELEASED. There is no "unclaim" on
-- success, on failure, or on error. Releasing it is precisely how the
-- duplicate run this table exists to prevent would come back: a turn that
-- failed halfway, after its tool had already sent something, is exactly the
-- turn that must not be retried. A row here means "this was attempted", not
-- "this is in flight", and attempted is the thing worth remembering.
--
-- Rows are swept after 24 hours by the same statement path that writes them,
-- so the table cannot grow without bound. That is long after any turn could
-- still be running, and long enough that a person reloading a conversation
-- they left open overnight still cannot re-run yesterday's turn.
--
-- No foreign keys: chat_id and agent_id belong to Open WebUI's tables, which
-- this service does not own and which can drop rows at any time. A cascade
-- would silently delete the claim and re-enable the duplicate.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.agent_turn_claim (
    user_email TEXT NOT NULL,
    chat_id    TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    after_id   TEXT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_email, chat_id, agent_id, after_id)
);

-- The sweep runs on the same path as every claim, so it must not table scan.
CREATE INDEX IF NOT EXISTS agent_turn_claim_claimed_at_idx
    ON tasks.agent_turn_claim (claimed_at);
