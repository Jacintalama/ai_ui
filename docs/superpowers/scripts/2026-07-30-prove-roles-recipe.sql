-- Prove the admin/regular-user RLS recipe we are about to teach the builder.
-- Runs in a THROWAWAY database. Never touches `openwebui`.
--
-- Simulates the two Supabase things a plain Postgres lacks: the `auth` schema
-- with `auth.uid()` reading the JWT sub, and the `authenticated` role.

\set ON_ERROR_STOP on

-- ---------- Supabase shims ----------
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text);

CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
END $$;

-- ==========================================================================
-- THE RECIPE (verbatim what the builder will be told to emit)
-- ==========================================================================

CREATE TABLE profiles (
  id    uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text,
  role  text NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user'))
);
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- SECURITY DEFINER is the whole point: a policy on `profiles` that queried
-- `profiles` directly would recurse. This runs as the owner, so it does not
-- re-enter RLS. search_path is pinned so it cannot be hijacked.
CREATE FUNCTION public.is_admin() RETURNS boolean
  LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public, pg_temp AS
$$ SELECT EXISTS (
     SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin'
   ) $$;

CREATE POLICY profiles_read_self_or_admin ON profiles
  FOR SELECT TO authenticated
  USING (id = auth.uid() OR public.is_admin());

-- an ordinary app table
CREATE TABLE items (
  id      bigserial PRIMARY KEY,
  user_id uuid NOT NULL DEFAULT auth.uid(),
  title   text
);
ALTER TABLE items ENABLE ROW LEVEL SECURITY;

CREATE POLICY items_owner_or_admin ON items
  FOR ALL TO authenticated
  USING (user_id = auth.uid() OR public.is_admin())
  WITH CHECK (user_id = auth.uid() OR public.is_admin());

-- first person to sign up becomes admin; everyone after is a regular user
CREATE FUNCTION public.handle_new_user() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  INSERT INTO public.profiles (id, email, role)
  VALUES (NEW.id, NEW.email,
          CASE WHEN NOT EXISTS (SELECT 1 FROM public.profiles)
               THEN 'admin' ELSE 'user' END);
  RETURN NEW;
END $$;

CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

GRANT USAGE ON SCHEMA public, auth TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON profiles, items TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE items_id_seq TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_admin(), auth.uid() TO authenticated;

-- ==========================================================================
-- TESTS
-- ==========================================================================
\echo ''
\echo '=== 1. signup trigger: first user admin, second user regular ==='
INSERT INTO auth.users (id, email) VALUES
  ('11111111-1111-1111-1111-111111111111', 'boss@example.com'),
  ('22222222-2222-2222-2222-222222222222', 'staff@example.com');
SELECT '  ' || email || ' -> ' || role AS result FROM profiles ORDER BY role;

\echo ''
\echo '=== 2. each user inserts one row (as the authenticated role, RLS on) ==='
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false);
INSERT INTO items (title) VALUES ('admin item');
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false);
INSERT INTO items (title) VALUES ('staff item');
RESET ROLE;
SELECT '  rows in items (bypassing RLS as owner): ' || count(*) AS result FROM items;

\echo ''
\echo '=== 3. THE ASSERTION: admin sees BOTH, regular user sees ONLY OWN ==='
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false);
SELECT '  admin sees ' || count(*) || ' of 2 rows (want 2)' AS result FROM items;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false);
SELECT '  staff sees ' || count(*) || ' of 2 rows (want 1)' AS result FROM items;
SELECT '  staff sees only its own: ' || bool_and(title = 'staff item') AS result FROM items;

\echo ''
\echo '=== 4. is_admin() does not recurse or error on the profiles policy ==='
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false);
SELECT '  staff reading profiles: ' || count(*) || ' row(s) (want 1, its own)' AS result FROM profiles;
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false);
SELECT '  admin reading profiles: ' || count(*) || ' row(s) (want 2, all)' AS result FROM profiles;

\echo ''
\echo '=== 5. a regular user cannot promote itself to admin ==='
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false);
DO $$
BEGIN
  UPDATE public.profiles SET role = 'admin' WHERE id = auth.uid();
  IF (SELECT role FROM public.profiles WHERE id = auth.uid()) = 'admin' THEN
    RAISE NOTICE '  PRIVILEGE ESCALATION: staff promoted itself';
  ELSE
    RAISE NOTICE '  blocked: staff is still a regular user';
  END IF;
EXCEPTION WHEN insufficient_privilege OR others THEN
  RAISE NOTICE '  blocked by policy: %', SQLERRM;
END $$;
RESET ROLE;
SELECT '  final role of staff: ' || role AS result FROM profiles WHERE email = 'staff@example.com';
