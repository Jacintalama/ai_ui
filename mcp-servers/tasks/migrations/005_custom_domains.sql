-- Custom domains for published apps. One row in tasks.published_apps may
-- optionally have its own externally-pointed domain (e.g. mybrand.com)
-- pointing to our server. Caddy's on-demand TLS uses our /__caddy/check_ask
-- endpoint to gate cert issuance — only verified domains in this table get
-- a cert, preventing rogue Let's Encrypt rate-limit abuse.

ALTER TABLE tasks.published_apps ADD COLUMN IF NOT EXISTS custom_domain TEXT;
ALTER TABLE tasks.published_apps ADD COLUMN IF NOT EXISTS custom_domain_verified_at TIMESTAMPTZ;

-- Custom domain must be globally unique across all published apps.
CREATE UNIQUE INDEX IF NOT EXISTS published_apps_custom_domain_idx
    ON tasks.published_apps (custom_domain)
    WHERE custom_domain IS NOT NULL;
