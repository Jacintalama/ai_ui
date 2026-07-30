-- The HARDENED recipe, verbatim as the builder is now told to emit it.
-- Supersedes 2026-07-30-prove-roles-recipe.sql, which proved the pre-review
-- version. Runs in a throwaway DB. Never touches `openwebui`.
--
-- Exists because the taught prompt drifted from the proof during hardening
-- (CREATE OR REPLACE, ON CONFLICT, the guard trigger, enable-RLS on app
-- tables). The drift test caught it. Proof and prompt must match.
\set ON_ERROR_STOP on

-- ---------- Supabase shims (auth.uid() reads the JWT sub) ----------
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text,
                         created_at timestamptz DEFAULT now());
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
END $$;

-- ==================== THE TAUGHT RECIPE, VERBATIM ====================
-- 1 & 2
CREATE TABLE profiles (id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, email text, role text NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')));
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
-- 3
CREATE FUNCTION public.is_admin() RETURNS boolean LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public, pg_temp AS $$ SELECT EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin') $$;
-- 4
CREATE POLICY profiles_read_self_or_admin ON profiles FOR SELECT TO authenticated USING (id = auth.uid() OR public.is_admin());
-- 5
CREATE POLICY profiles_admin_manages ON profiles FOR UPDATE TO authenticated USING (public.is_admin()) WITH CHECK (public.is_admin());
-- 6 & 7  (guard: role changes need an admin, whatever policies exist)
CREATE FUNCTION public.guard_role_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$ BEGIN IF NEW.role IS DISTINCT FROM OLD.role AND NOT public.is_admin() THEN RAISE EXCEPTION 'only an admin can change a role'; END IF; RETURN NEW; END $$;
CREATE TRIGGER profiles_guard_role BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION public.guard_role_change();
-- 8a/8b/8c on an app table
CREATE TABLE items (id bigserial PRIMARY KEY, title text);
ALTER TABLE items ADD COLUMN user_id uuid NOT NULL DEFAULT auth.uid();
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
CREATE POLICY items_owner_or_admin ON items FOR ALL TO authenticated USING (user_id = auth.uid() OR public.is_admin()) WITH CHECK (user_id = auth.uid() OR public.is_admin());
-- 9  (leftover anon-allow must be dropped; prove the statement is valid)
DROP POLICY IF EXISTS "allow_all_anon" ON items;
-- 10 & 11
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$ BEGIN INSERT INTO public.profiles (id, email, role) VALUES (NEW.id, NEW.email, CASE WHEN NOT EXISTS (SELECT 1 FROM public.profiles) THEN 'admin' ELSE 'user' END) ON CONFLICT (id) DO NOTHING; RETURN NEW; END $$;
CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

GRANT USAGE ON SCHEMA public, auth TO authenticated, anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON profiles, items TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE items_id_seq TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_admin(), auth.uid() TO authenticated;

-- ==================== TESTS ====================
\echo ''
\echo '=== 1. signup trigger: first admin, second regular ==='
INSERT INTO auth.users (id, email) VALUES
  ('11111111-1111-1111-1111-111111111111', 'boss@example.com'),
  ('22222222-2222-2222-2222-222222222222', 'staff@example.com');
SELECT '  ' || email || ' -> ' || role AS r FROM profiles ORDER BY role;

\echo ''
\echo '=== 2. idempotency: re-running step 10 must NOT fail ==='
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$ BEGIN INSERT INTO public.profiles (id, email, role) VALUES (NEW.id, NEW.email, CASE WHEN NOT EXISTS (SELECT 1 FROM public.profiles) THEN 'admin' ELSE 'user' END) ON CONFLICT (id) DO NOTHING; RETURN NEW; END $$;
\echo '  CREATE OR REPLACE ran twice with no error'

\echo ''
\echo '=== 3. ON CONFLICT: a duplicate signup must not break sign-up ==='
INSERT INTO auth.users (id, email) VALUES
  ('22222222-2222-2222-2222-222222222222', 'dupe@example.com')
  ON CONFLICT (id) DO NOTHING;
SELECT '  profiles rows (still 2, no exception raised): ' || count(*) AS r FROM profiles;

\echo ''
\echo '=== 4. admin sees all, regular user sees own ==='
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',false) \gset
INSERT INTO items (title) VALUES ('admin item');
SELECT set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',false) \gset
INSERT INTO items (title) VALUES ('staff item');
SELECT set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',false) \gset
SELECT '  admin sees ' || count(*) || ' of 2 (want 2)' AS r FROM items;
SELECT set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',false) \gset
SELECT '  staff sees ' || count(*) || ' of 2 (want 1)' AS r FROM items;
RESET ROLE;

\echo ''
\echo '=== 5. guard trigger holds even with a permissive self-update policy ==='
CREATE POLICY profiles_update_own ON profiles FOR UPDATE TO authenticated
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',false) \gset
DO $$ BEGIN
  UPDATE public.profiles SET role = 'admin' WHERE id = auth.uid();
  RAISE NOTICE '  ESCALATION HOLE: staff promoted itself';
EXCEPTION WHEN others THEN
  RAISE NOTICE '  blocked: %', SQLERRM;
END $$;
UPDATE profiles SET email = 'staff.edited@example.com' WHERE id = auth.uid();
\echo '  staff edited its own email with no error = still usable'
SELECT set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',false) \gset
UPDATE profiles SET role = 'admin' WHERE email LIKE 'staff%';
\echo '  admin promoted staff with no error = admins still work'
RESET ROLE;
SELECT '  final: ' || email || ' -> ' || role AS r FROM profiles ORDER BY email;
