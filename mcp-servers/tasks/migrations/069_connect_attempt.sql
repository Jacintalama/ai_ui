-- 069: every attempt to connect an app, and how far it got.
--
-- Measured 2026-11-16: nine people are on this platform and ONE has ever
-- connected anything. Asked whether the other eight ever TRIED, the honest
-- answer was that we could not know. Every failure path in the OAuth
-- callback was a logger.warning and nothing else, and a container log starts
-- at the last deploy: 41,651 lines beginning Friday 14:10 UTC with zero
-- oauth lines in them. We deploy several times a day, so each deploy
-- destroyed the only record there was.
--
-- That left two situations indistinguishable, and they call for opposite
-- responses: nobody wants connectors, or connectors are broken for everybody
-- who is not Ralph. One row per attempt tells them apart, and keeps telling
-- them apart after the next rebuild.
--
-- NOT ONE WORD THE VENDOR SAID IS STORED HERE, for the reason migration 068
-- already states on itself: vendors echo the request back in their errors,
-- and Trello's credential rides in its query string, so a free-text column
-- would be a credential store with extra steps.
--
-- Which is why `stage` is checked by SHAPE rather than against a list of
-- names. The property that matters is that no stage can be a sentence, a
-- URL, an address or a token: lowercase letters and underscores, 3 to 24
-- characters. A CHECK enumerating today's fourteen names would have to be
-- migrated every time one is added, and the failure mode of forgetting is
-- that recording silently stops, since connect_attempt.record fails open on
-- purpose so that nobody loses a connection over a log row. The closed set
-- of names lives in connect_attempt.STAGES, where a test holds it against
-- the call sites in both directions.
--
-- http_status is kept as an INTEGER because 401, 403 and 503 need three
-- different answers from us, and bounded to real status codes so that the
-- column cannot quietly become somewhere an error body goes.
--
-- email may be empty, and that is a fact rather than an omission: a callback
-- whose state is expired, replayed or forged has no verified email to record,
-- because the state is the thing that carried it. An empty email still
-- answers "somebody tried this provider and it broke before we knew who".
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.connect_attempt (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT        NOT NULL DEFAULT '',
    provider    TEXT        NOT NULL DEFAULT '',
    stage       TEXT        NOT NULL,
    http_status INTEGER,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT connect_attempt_stage_is_a_name
        CHECK (stage ~ '^[a-z][a-z_]{2,23}$'),
    CONSTRAINT connect_attempt_status_is_a_status
        CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599)
);

-- Newest first is the only way this is ever read.
CREATE INDEX IF NOT EXISTS connect_attempt_at_idx
    ON tasks.connect_attempt (at DESC);

-- "Did anyone get Notion to work" is the second question after "did anyone
-- try", so provider leads this one.
CREATE INDEX IF NOT EXISTS connect_attempt_provider_at_idx
    ON tasks.connect_attempt (provider, at DESC);
