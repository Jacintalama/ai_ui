-- Migration 013: Add tasks.schedules — heartbeat scheduler v1
--
-- Stores cron-triggered agent runs. The tasks service polls every minute and
-- dispatches matching rows through the existing remote_executor pipeline.
-- See docs/superpowers/specs/2026-05-18-heartbeat-scheduler-design.md.

CREATE TABLE IF NOT EXISTS tasks.schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_email TEXT NOT NULL,
  name TEXT NOT NULL,
  cron_expr TEXT NOT NULL,
  tz TEXT NOT NULL DEFAULT 'Asia/Manila',
  persona TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_run_at TIMESTAMPTZ NULL,
  last_run_status TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS schedules_enabled_idx
  ON tasks.schedules(enabled) WHERE enabled = TRUE;
