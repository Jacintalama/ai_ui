-- 045: a change an agent wants to make, waiting for the person to say yes.
--
-- The two-phase confirm this backs is enforced by this row, not by the
-- model: proposing writes here and changes nothing, and applying is the
-- only path that can start a build. A model that decides to skip the
-- confirmation cannot, because there is no other way in.
--
-- A table rather than process memory because the tasks service is not
-- guaranteed to be a single worker, and a proposal made on one worker and
-- confirmed on another must not silently vanish.
--
-- used_at is what makes a token single use. It is set by the same UPDATE
-- that reads the row, so two confirms racing cannot both win.
--
-- Idempotent: db.py re-runs every migration on every startup.
CREATE TABLE IF NOT EXISTS tasks.agent_proposals (
    token        TEXT PRIMARY KEY,
    user_email   TEXT        NOT NULL,
    slug         TEXT        NOT NULL,
    description  TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at      TIMESTAMPTZ
);

-- Proposals are always looked up by token, and swept by age.
CREATE INDEX IF NOT EXISTS agent_proposals_created_idx
    ON tasks.agent_proposals (created_at);
