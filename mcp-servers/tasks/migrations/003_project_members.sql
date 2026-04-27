-- Per-project access control. One row = one user granted access to one slug.
-- Created when an admin creates a BUILD task (backfilled for existing ones)
-- and when an admin invites someone to a project.

CREATE TABLE IF NOT EXISTS tasks.project_members (
    slug        TEXT        NOT NULL,
    user_email  TEXT        NOT NULL,
    role        TEXT        NOT NULL DEFAULT 'editor'
                            CHECK (role IN ('owner', 'editor', 'viewer')),
    added_by    TEXT        NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (slug, user_email)
);

CREATE INDEX IF NOT EXISTS project_members_user_idx
    ON tasks.project_members (user_email);

-- Backfill: every existing built app gets its assignee as owner.
INSERT INTO tasks.project_members (slug, user_email, role, added_by)
SELECT DISTINCT ON (built_app_slug, assignee_email)
       built_app_slug, assignee_email, 'owner', assignee_email
FROM   tasks.items
WHERE  built_app_slug IS NOT NULL
  AND  assignee_email IS NOT NULL
ON CONFLICT DO NOTHING;
