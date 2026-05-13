-- Down migration 012: drop the agent_host audit column.

ALTER TABLE tasks.executions
  DROP COLUMN IF EXISTS agent_host;
