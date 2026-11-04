-- 066: a person can have skills of their own (user_skills.py).
--
-- Specified in docs/superpowers/specs/2026-09-09-agent-skill-writer-design.md
-- and unbuilt until 2026-11-03. The table is that design's, with the number
-- moved on: it was written as 049 when 049 was next.
--
-- Built-in skills stay FILES in the image, read from agent_skills/. They
-- ship, they are the same for everybody, and they need no database. This is
-- only for what somebody writes for themselves.
--
-- The unique index is on (user_email, name), not on name. Two people may
-- each have a skill called `inbox-triage`; they are different skills and
-- neither can see the other's.
--
-- A name may collide with a built-in one, and when it does the person's own
-- wins FOR THAT PERSON. Anything else means a deploy that adds a built-in
-- skill silently replaces one somebody wrote, which is the worse failure.
--
-- `tools` is text[] because it is a list the code reads as a list, and a
-- comma-joined string here would be parsed back by every reader. The email
-- cursor's seen_ids went the other way on purpose, because nothing joins on
-- those and they are read from psql by hand.
--
-- Additive and idempotent: db.py re-runs every migration on each startup, so
-- a failure here would block every later one.

CREATE TABLE IF NOT EXISTS tasks.user_skill (
    id           UUID PRIMARY KEY,
    user_email   TEXT NOT NULL,
    -- Agent Skills spec shape: lowercase letters, digits and hyphens.
    name         TEXT NOT NULL,
    -- What it is for, and WHEN to use it. Shown in the picker.
    description  TEXT NOT NULL,
    -- The tools this skill needs, so the form can tell somebody to connect
    -- Gmail rather than letting the skill quietly do nothing.
    tools        TEXT[] NOT NULL DEFAULT '{}',
    -- The instructions, pasted whole into the brief of every agent holding
    -- this skill, on every turn. That is why it is capped in code.
    body         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS user_skill_owner_name
    ON tasks.user_skill (user_email, name);

-- Every read is "this person's skills", so the owner leads the index.
CREATE INDEX IF NOT EXISTS user_skill_owner
    ON tasks.user_skill (user_email);
