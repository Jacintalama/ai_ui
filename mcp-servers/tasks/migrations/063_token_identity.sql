-- 063: One account, one key. Per-user token rows are keyed by the address.
--
-- Read off production on 2026-10-29: one account had a row in all three
-- Google token tables keyed by its Open WebUI user id rather than its
-- address,
--
--     gmail_tokens     d741f063-d6b4-4d28-9abb-9bf30b43fa9e
--     gdrive_tokens    d741f063-d6b4-4d28-9abb-9bf30b43fa9e
--     calendar_tokens  d741f063-d6b4-4d28-9abb-9bf30b43fa9e
--
-- alongside a correct row keyed by the address. Every read asks by address,
-- so the id-keyed rows were written, never read, and never reported: the
-- account looked connected in the browser and unconnected to everything
-- else, in three services at once, with no error anywhere.
--
-- All three came from one `connect=all` consent, which writes all three
-- tables from a single identity. That identity came from the browser, which
-- took it from the Open WebUI JWT, which carries an id and no address. The
-- browser no longer does that, and the Gmail service now refuses to store a
-- key that is not an address (account_identity.py). This repairs what the
-- bug already wrote, and the CHECK at the end is what keeps the promise if
-- some other client ever tries the same thing.
--
-- Additive and idempotent: db.py re-runs every migration on each startup,
-- and after the first run there is nothing left to repair.

DO $$
DECLARE
    tbl   text;
    n_del int;
    n_key int;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY['gmail_tokens', 'gdrive_tokens',
                                   'calendar_tokens'])
    LOOP
        -- calendar_tokens is created lazily, on the first unified connect,
        -- so it may not exist yet on a fresh box.
        IF to_regclass('public.' || tbl) IS NULL THEN
            CONTINUE;
        END IF;

        -- An id-keyed row whose account also has an address-keyed row is dead
        -- weight. Every read has only ever asked by address, so the address
        -- row is the one that has been working: drop the id row rather than
        -- overwrite a live credential with a stale one.
        EXECUTE format($f$
            DELETE FROM public.%I AS bad
             USING public."user" AS u, public.%I AS good
             WHERE bad.user_email = u.id
               AND good.user_email = u.email
        $f$, tbl, tbl);
        GET DIAGNOSTICS n_del = ROW_COUNT;

        -- An id-keyed row with no address-keyed twin is a connection that only
        -- looks missing. Give it the right key and it works again, with no
        -- need to ask anyone to reconnect.
        EXECUTE format($f$
            UPDATE public.%I AS bad
               SET user_email = u.email
              FROM public."user" AS u
             WHERE bad.user_email = u.id
               AND NOT EXISTS (SELECT 1 FROM public.%I AS g
                                WHERE g.user_email = u.email)
        $f$, tbl, tbl);
        GET DIAGNOSTICS n_key = ROW_COUNT;

        IF n_del > 0 OR n_key > 0 THEN
            RAISE NOTICE '063 %: dropped % duplicate, rekeyed %',
                         tbl, n_del, n_key;
        END IF;

        -- The assertion. Deliberately loose: it only has to tell an address
        -- apart from a user id, and a tighter rule risks rejecting somebody's
        -- real address. A row left over that resolves to no account at all
        -- would fail this, which is why it is added NOT VALID: new writes are
        -- checked, and nothing already stored is deleted to satisfy it.
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = tbl || '_key_is_an_address') THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I '
                'CHECK (user_email LIKE %L) NOT VALID',
                tbl, tbl || '_key_is_an_address', '%@%');
        END IF;
    END LOOP;
END $$;
