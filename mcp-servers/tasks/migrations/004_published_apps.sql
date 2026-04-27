-- Track which built apps are published live at <slug>.ai-ui.coolestdomain.win.
-- One row per slug. Presence of a row = published. Removal = unpublished.
CREATE TABLE IF NOT EXISTS tasks.published_apps (
    slug          TEXT PRIMARY KEY,
    published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_by  TEXT NOT NULL,
    public_host   TEXT NOT NULL  -- e.g. "ai-ui-landing.ai-ui.coolestdomain.win"
);

CREATE INDEX IF NOT EXISTS published_apps_published_at_idx
    ON tasks.published_apps (published_at DESC);
