-- 061: Approvals from anywhere (agent_approvals.py, routes_approvals.py).
--
-- Until now a question an agent on Ask stopped to ask lived only in the
-- chat it came from: the main chat's held call, the office thread's bubble,
-- a bot's buttons. An automation has no chat, so its agent could only read.
-- Now a held question is a row with an id, so it can be answered from the
-- Agents page, the main chat, or a route, and expires on its own; and a
-- person can set standing rules that answer the usual questions at once.
--
-- No message text in approval_rule; approval carries the held conversation
-- the way the chat's BotState row did, so the turn can pick up where it
-- stopped. Additive and idempotent: db.py re-runs every migration on boot.
CREATE TABLE IF NOT EXISTS tasks.approval (
    id            UUID PRIMARY KEY,
    user_email    TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    agent_name    TEXT NOT NULL DEFAULT '',
    -- automation, chat, api: where the turn that asked was running.
    origin        TEXT NOT NULL,
    -- The automation's id, or the chat's held-call state key, so an
    -- answer given elsewhere can finish what that place started.
    origin_ref    TEXT NOT NULL DEFAULT '',
    -- The tool calls held, and the conversation to resume with.
    calls         JSONB NOT NULL,
    conversation  JSONB NOT NULL,
    question      TEXT NOT NULL DEFAULT '',
    -- pending, approved, refused, expired
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    decided_at    TIMESTAMPTZ,
    -- page, chat, rule, api
    decided_via   TEXT,
    result        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS approval_pending
    ON tasks.approval (user_email, status, created_at DESC);

CREATE TABLE IF NOT EXISTS tasks.approval_rule (
    id            UUID PRIMARY KEY,
    user_email    TEXT NOT NULL,
    -- The tool's method name, or a pattern with * (send_*).
    tool          TEXT NOT NULL,
    -- allow or deny
    decision      TEXT NOT NULL,
    -- Text that must appear in the call's arguments for the rule to
    -- apply, case blind; empty applies to every call of the tool.
    when_contains TEXT NOT NULL DEFAULT '',
    label         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS approval_rule_owner
    ON tasks.approval_rule (user_email, created_at DESC);
