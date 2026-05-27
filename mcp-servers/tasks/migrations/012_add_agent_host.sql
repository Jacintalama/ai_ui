-- Migration 012: Add agent_host column to tasks.executions
--
-- Records which agent host ran an execution. NULL for LocalExecutor;
-- populated by RemoteExecutor with the AGENT_HOST env var. Used for
-- audit + forensics ("which VM ran this build?").
--
-- Applied to live ai-ui.coolestdomain.win at 2026-05-13 ~10:08 UTC,
-- after the Tasks 1-3 deploy that introduced the writeback code path
-- (which was guarded by try/except ProgrammingError until this migration).

ALTER TABLE tasks.executions
  ADD COLUMN IF NOT EXISTS agent_host TEXT NULL;
