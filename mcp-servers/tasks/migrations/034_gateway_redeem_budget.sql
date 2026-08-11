-- 034: the pairing lockout counts against the account doing the guessing,
-- not against the code row.
--
-- 033 counted failed redemptions on gateway_pairing_codes.attempts. Two
-- problems, both caught in review before any of this shipped:
--   1. resolve() skipped attempt-exhausted rows and minted a fresh one with the
--      counter back at zero, so any ordinary message from the victim handed an
--      attacker a new budget.
--   2. a wrong guess matches no row, so the only way to count it was to
--      increment EVERY live code. Five bad guesses would have locked out every
--      pending pairing on the platform.
-- Counting against the signed-in account fixes both: a guesser can only burn
-- their own budget, and nobody else's.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.gateway_redeem_budget (
    email             TEXT        PRIMARY KEY,
    failures          INT         NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_until      TIMESTAMPTZ
);
