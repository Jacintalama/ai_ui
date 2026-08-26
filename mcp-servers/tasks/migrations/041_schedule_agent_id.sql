-- 041: let a schedule name one of the user's AI agents.
--
-- Null means what schedules have always done: the Claude Code CLI executor,
-- with the persona prefix and MEMORY.md. Every row that exists today is in
-- that state, so the column has to be nullable and nothing is backfilled.
--
-- Deliberately NOT a new `kind`. schedules.kind is already 'agent' or 'video',
-- where 'agent' means the CLI executor, so a scheduled task is already called
-- an agent and it is not the same thing as an AI Agent. Adding a third value
-- there would deepen a collision instead of avoiding it.
--
-- No foreign key to the model table. Open WebUI owns public.model, an agent
-- can be deleted from the web at any time, and a cascade or a restrict would
-- either destroy the user's schedule or block their delete. The scheduler
-- checks at run time and falls back instead.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS agent_id TEXT;
