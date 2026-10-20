-- 057: what Jev decided about a message to the whole team.
--
-- Before the lead triages a team message, Jev (TypeSafe's decision model) is
-- asked two questions: is it one answer or a job, and which agent should take
-- it (agent_decider). One row per call, kept so the plain debug page can show
-- each decision with its confidence and the path the round took, and so the
-- confidence threshold can be checked against real messages.
--
-- No message text, on purpose: the person's words live in their chat, and a
-- second copy here would outlive a chat they delete.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.agent_decision (
    id               BIGSERIAL PRIMARY KEY,
    user_email       TEXT NOT NULL,
    chat_id          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider         TEXT NOT NULL,
    model            TEXT,
    kind             TEXT,
    kind_confidence  REAL,
    agent_id         TEXT,
    agent_confidence REAL,
    -- one_agent, plan or fallback (agent_decider.PATH_*).
    path             TEXT NOT NULL,
    reason           TEXT,
    ms               INT,
    input_tokens     INT,
    cost_usd         NUMERIC(12,8)
);

CREATE INDEX IF NOT EXISTS agent_decision_user_time
    ON tasks.agent_decision (user_email, created_at DESC);
