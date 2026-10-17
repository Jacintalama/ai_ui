-- 056: which app build a run is.
--
-- An agent that starts an App Builder job (routes_code /create and /apply,
-- on the agent's behalf) is working until that job ends, not until its chat
-- turn ends: the turn is over in seconds, the build takes minutes, and the
-- office showed the agent as Ready with the build still running
-- (screenshot, 2026-10-17, "it should be in progress working"). The run
-- opened for the build carries the tasks.items id, so the execution
-- pipeline can close it when the item finishes (agent_activity
-- finish_task_runs). NULL on every other run.
ALTER TABLE tasks.agent_run
    ADD COLUMN IF NOT EXISTS task_id UUID;

CREATE INDEX IF NOT EXISTS agent_run_task_idx
    ON tasks.agent_run (task_id)
    WHERE task_id IS NOT NULL;
