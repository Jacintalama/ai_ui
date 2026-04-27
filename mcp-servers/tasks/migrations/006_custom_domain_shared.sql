-- Custom domain is now treated as a PARENT domain. The app's public URL is
-- <slug>.<custom_domain>, so multiple apps may share the same parent (each
-- gets its own subdomain there). Drop the unique constraint and replace
-- with a regular non-unique index for fast lookups.

DROP INDEX IF EXISTS tasks.published_apps_custom_domain_idx;
CREATE INDEX IF NOT EXISTS published_apps_custom_domain_idx
    ON tasks.published_apps (custom_domain)
    WHERE custom_domain IS NOT NULL;

-- Reset existing verifications: the meaning changed (parent vs full host),
-- so users must re-add a DNS record for <slug>.<parent> and re-verify.
UPDATE tasks.published_apps
   SET custom_domain_verified_at = NULL
 WHERE custom_domain IS NOT NULL;
