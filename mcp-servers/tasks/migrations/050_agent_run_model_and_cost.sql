-- 050: which model answered an agent run, why it moved to the paid model,
-- and what it cost.
--
-- Nothing recorded any of this. Agent turns reach Open WebUI through its API,
-- which writes no chat rows, Langfuse holds 0 traces, and agent_run (044)
-- kept only who ran and when. From 2026-09-17 a free agent can move to the
-- paid model on its own, so the daily cap needs something to count and the
-- owner needs something to read.
--
-- escalation is the reason a run moved (build, code, error, sticky,
-- heavy_tool, empty_answer, pool_spent, rounds_cap, long_message,
-- long_conversation) and NULL for a run that stayed where it started. It is
-- written the moment the run moves, not when it finishes, because the cap
-- counts these rows while a room of agents is still answering.
--
-- cost_usd is NULL when it is not known (a model with no price, or a paid
-- reply that carried no usage), never 0, so a row cannot claim a paid run
-- was free.
--
-- A run can use a free id and the paid model in the same turn. Then model
-- is the paid model (once any paid completion answered), prompt_tokens and
-- completion_tokens are totals over every completion, free ones included,
-- and cost_usd prices only the paid completions. So cost_usd is not
-- prompt_tokens and completion_tokens times the price on a mixed run; check
-- it against the paid completions' counts, which the tasks log carries one
-- line each ("paid completion for <agent> on <model>: N prompt tokens, M
-- completion tokens"). No separate paid token columns: that would be two
-- more columns for a check the log already answers.
--
-- Idempotent: db.py re-runs every migration on every startup. ADD COLUMN IF
-- NOT EXISTS only; the rollback lives in rollbacks/ and is applied by hand.
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS model TEXT;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS escalation TEXT;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS completion_tokens INTEGER;
ALTER TABLE tasks.agent_run ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION;

-- The cap's question: this person's runs that moved, since midnight UTC.
CREATE INDEX IF NOT EXISTS agent_run_paid_today_idx
    ON tasks.agent_run (lower(user_email), started_at)
    WHERE escalation IS NOT NULL;
