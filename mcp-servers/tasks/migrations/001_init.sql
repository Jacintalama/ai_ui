CREATE SCHEMA IF NOT EXISTS tasks;

CREATE TABLE IF NOT EXISTS tasks.items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id      UUID NOT NULL,
    action_type     TEXT NOT NULL CHECK (action_type IN ('RESEARCH','BUILD','INTEGRATE','ASK_USER')),
    assignee_name   TEXT NOT NULL,
    assignee_email  TEXT NOT NULL,
    description     TEXT NOT NULL,
    query           TEXT,
    priority        TEXT NOT NULL CHECK (priority IN ('CRITICAL','IMPORTANT','NICE_TO_HAVE')),
    status          TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','claimed_manual','running','awaiting_input','completed','failed')),
    mode            TEXT CHECK (mode IN ('ai','manual')),
    result          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS items_assignee_status_idx ON tasks.items (assignee_email, status);
CREATE INDEX IF NOT EXISTS items_assignee_completed_idx ON tasks.items (assignee_email, completed_at DESC);
CREATE INDEX IF NOT EXISTS items_meeting_idx ON tasks.items (meeting_id);

-- Idempotency on webhook ingestion
CREATE UNIQUE INDEX IF NOT EXISTS items_meeting_desc_uniq
    ON tasks.items (meeting_id, md5(description));

CREATE TABLE IF NOT EXISTS tasks.executions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks.items(id) ON DELETE CASCADE,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','succeeded','failed','needs_input')),
    log          TEXT NOT NULL DEFAULT '',
    error        TEXT
);

-- Only one execution per task may be 'running' at a time
CREATE UNIQUE INDEX IF NOT EXISTS executions_one_running
    ON tasks.executions (task_id) WHERE status = 'running';

CREATE OR REPLACE FUNCTION tasks._touch_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS items_touch_updated_at ON tasks.items;
CREATE TRIGGER items_touch_updated_at BEFORE UPDATE ON tasks.items
    FOR EACH ROW EXECUTE FUNCTION tasks._touch_updated_at();
