-- 058: Jev's small checks (agent_jev), and how urgent a team message is.
--
-- Beside the team decision (057), Jev now answers smaller questions the
-- agents used to answer with word lists: is a message a plain question, is a
-- turn worth remembering, which app version did the person mean, did a reply
-- answer the message, is the person done with the agent. One row per call,
-- for the Debug page and for checking each cut-off against real use.
--
-- No message text, on purpose, for the reason 057 gives.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.
CREATE TABLE IF NOT EXISTS tasks.jev_check (
    id           BIGSERIAL PRIMARY KEY,
    user_email   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- plain_question, worth_remembering, rollback_version, reply_answers,
    -- release (agent_jev.PURPOSE_*).
    purpose      TEXT NOT NULL,
    model        TEXT,
    -- The option picked for a Choice; empty for a yes or no question.
    choice       TEXT,
    -- A Choice's confidence, or a yes or no question's probability of yes.
    value        REAL,
    -- What the code did with the answer, or fallback.
    outcome      TEXT,
    reason       TEXT,
    ms           INT,
    input_tokens INT,
    cost_usd     NUMERIC(12,8)
);

CREATE INDEX IF NOT EXISTS jev_check_user_time
    ON tasks.jev_check (user_email, created_at DESC);

-- A third question in the decider's call (a Score): can wait, normal or
-- urgent, with its confidence. Shown on the Debug page; nothing acts on it.
ALTER TABLE tasks.agent_decision ADD COLUMN IF NOT EXISTS urgency TEXT;
ALTER TABLE tasks.agent_decision
    ADD COLUMN IF NOT EXISTS urgency_confidence REAL;
