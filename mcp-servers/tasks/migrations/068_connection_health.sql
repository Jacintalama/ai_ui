-- 068: whether a stored credential still works, and when we last learned it.
--
-- A card said Connected for as long as a credential was STORED. Connecting
-- proved it once and nothing proved it again, so a revoked token left the
-- card reading Connected until some tool call failed in a chat, which is the
-- worst place to find out. Measured 2026-11-12: a GitHub credential on this
-- platform had been answering 401 for days behind a card saying Connected.
--
-- check_ok is deliberately NULLABLE WITH NO DEFAULT. NULL means "nothing has
-- been learned about this one", which is the honest state for every row that
-- exists when this migration runs and for every connection nobody has used
-- since. A default of false would accuse every connection on the platform at
-- once; a default of true would be a second thing asserting something nobody
-- checked, which is the bug this migration exists to fix.
--
-- There is no column for what the vendor SAID, and there must not be. Vendors
-- echo the request back in their errors and Trello's credential rides in its
-- query string, so a free-text column here is a credential store with extra
-- steps. A boolean and a timestamp cannot leak one, and the sentence a person
-- reads is composed from the app's name instead.
--
-- Only a 401 ever writes false. A 403 is a plan limit, a quota or a
-- permission far more often than a bad token: see PR #182, where ClickUp's
-- paywall answer had somebody told to reconnect a credential that had just
-- read his whole workspace.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.user_connections
    ADD COLUMN IF NOT EXISTS check_ok BOOLEAN;

ALTER TABLE tasks.user_connections
    ADD COLUMN IF NOT EXISTS checked_at TIMESTAMPTZ;
