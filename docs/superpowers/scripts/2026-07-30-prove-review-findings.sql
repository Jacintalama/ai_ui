-- Test the code-review findings on the roles recipe BEFORE changing the prompt.
-- Fresh roles_probe DB, recipe + admin-update policy already applied.
--
-- Purpose: confirm the two holes are real, and check whether the reviewer's
-- suggested fix for the escalation hole actually works. Suggested fixes get
-- tested, not trusted.
\set ON_ERROR_STOP off

UPDATE profiles SET role = 'user' WHERE email = 'staff@example.com';

\echo '############ FINDING 1: a policy WITHOUT enable-RLS is inert ############'
-- Step 6 of the taught recipe gives the column + policy but never says
-- ALTER TABLE ... ENABLE ROW LEVEL SECURITY. Simulate a model that follows it
-- literally on a new table.
CREATE TABLE notes (id bigserial PRIMARY KEY,
                    user_id uuid NOT NULL DEFAULT auth.uid(), body text);
CREATE POLICY notes_owner_or_admin ON notes FOR ALL TO authenticated
  USING (user_id = auth.uid() OR public.is_admin())
  WITH CHECK (user_id = auth.uid() OR public.is_admin());
GRANT SELECT, INSERT, UPDATE, DELETE ON notes TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE notes_id_seq TO authenticated;
INSERT INTO notes (user_id, body) VALUES
  ('11111111-1111-1111-1111-111111111111', 'admin private note'),
  ('22222222-2222-2222-2222-222222222222', 'staff private note');

SELECT '  relrowsecurity on notes: ' || relrowsecurity::text AS r
  FROM pg_class WHERE relname = 'notes';
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
SELECT '  rows staff can see WITHOUT enable-RLS: ' || count(*)
       || ' of 2  (2 = HOLE CONFIRMED, policy is inert)' AS r FROM notes;
RESET ROLE;

ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
SELECT '  rows staff can see AFTER enable-RLS:    ' || count(*)
       || ' of 2  (1 = the fix works)' AS r FROM notes;
RESET ROLE;

\echo ''
\echo '######## FINDING 3: a leftover allow_all_anon ORs and opens it ########'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public, auth TO anon;
GRANT SELECT ON notes TO anon;
CREATE POLICY allow_all_anon ON notes FOR ALL TO anon USING (true) WITH CHECK (true);
SET ROLE anon;
SELECT '  rows a NOT-SIGNED-IN visitor can read: ' || count(*)
       || ' of 2  (2 = HOLE CONFIRMED, leftover policy ORs)' AS r FROM notes;
RESET ROLE;
DROP POLICY allow_all_anon ON notes;
SET ROLE anon;
SELECT '  after DROP POLICY:                     ' || count(*)
       || ' of 2  (0 = the fix works)' AS r FROM notes;
RESET ROLE;

\echo ''
\echo '#### FINDING 2: does the reviewer''s suggested REVOKE fix work? ####'
-- The suggestion: REVOKE UPDATE (role) ... FROM authenticated.
-- Concern: in Supabase EVERY signed-in user is `authenticated`, admins too.
REVOKE UPDATE (role) ON public.profiles FROM authenticated;
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
UPDATE profiles SET role = 'admin' WHERE id = auth.uid();
\echo '   ^ staff self-promote: error = blocked (intended)'
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false) \gset
UPDATE profiles SET role = 'admin' WHERE email = 'staff@example.com';
\echo '   ^ ADMIN promoting staff: error here = the suggested fix BREAKS admins'
RESET ROLE;
SELECT '  staff role after admin tried to promote: ' || role AS r
  FROM profiles WHERE email = 'staff@example.com';
GRANT UPDATE (role) ON public.profiles TO authenticated;  -- undo

\echo ''
\echo '#### FINDING 2 alternative: a BEFORE UPDATE guard trigger ####'
CREATE FUNCTION public.guard_role_change() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.role IS DISTINCT FROM OLD.role AND NOT public.is_admin() THEN
    RAISE EXCEPTION 'only an admin can change a role';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER profiles_guard_role BEFORE UPDATE ON profiles
  FOR EACH ROW EXECUTE FUNCTION public.guard_role_change();

-- worst case: someone later adds the canonical self-update policy
CREATE POLICY profiles_update_own ON profiles FOR UPDATE TO authenticated
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());

UPDATE profiles SET role = 'user' WHERE email = 'staff@example.com';
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
UPDATE profiles SET role = 'admin' WHERE id = auth.uid();
\echo '   ^ staff self-promote WITH a permissive self-update policy present:'
\echo '     an exception here = guard trigger holds the line'
UPDATE profiles SET email = 'staff.new@example.com' WHERE id = auth.uid();
\echo '   ^ staff editing its OWN email: no error = still usable'
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false) \gset
UPDATE profiles SET role = 'admin' WHERE email LIKE 'staff%';
\echo '   ^ ADMIN promoting staff: no error = admins still work'
RESET ROLE;
SELECT '  final: ' || email || ' -> ' || role AS r FROM profiles ORDER BY role;
