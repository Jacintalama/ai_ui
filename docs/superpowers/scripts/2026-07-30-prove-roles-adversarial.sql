-- Adversarial pass on the roles recipe. Runs on top of prove_roles_recipe.sql
-- plus prove_admin_update.sql in the roles_probe scratch DB.
--
-- Think like an attacker holding the app's PUBLIC anon key in a browser. The
-- anon key is not a secret, so RLS is the only boundary that exists.
\set ON_ERROR_STOP off

-- reset staff back to a regular user (prove_admin_update.sql promoted them)
UPDATE profiles SET role = 'user' WHERE email = 'staff@example.com';

SET ROLE authenticated;

\echo '=== A. can a regular user INSERT a profiles row for someone else? ==='
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
INSERT INTO profiles (id, email, role)
  VALUES ('33333333-3333-3333-3333-333333333333', 'attacker@example.com', 'admin');
\echo '   (an error above = correctly DENIED; no error = HOLE)'

\echo ''
\echo '=== B. can a regular user claim another users row on INSERT? ==='
INSERT INTO items (user_id, title)
  VALUES ('11111111-1111-1111-1111-111111111111', 'planted by staff');
\echo '   (an error above = correctly DENIED by WITH CHECK; no error = HOLE)'

\echo ''
\echo '=== C. can a regular user REASSIGN its row to someone else? ==='
UPDATE items SET user_id = '11111111-1111-1111-1111-111111111111'
  WHERE title = 'staff item';
RESET ROLE;
SELECT '   staff item still owned by staff: '
       || (user_id = '22222222-2222-2222-2222-222222222222')::text AS r
  FROM items WHERE title = 'staff item';

\echo ''
\echo '=== D. can a regular user read another users email from profiles? ==='
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
SELECT '   emails visible to staff: ' || coalesce(string_agg(email, ', '), '(none)') AS r
  FROM profiles;
\echo '   (must show ONLY staff@example.com)'

\echo ''
\echo '=== E. did the trigger INSERT work even with NO insert policy? ==='
RESET ROLE;
SELECT '   profiles rows created by the trigger: ' || count(*) AS r FROM profiles;
\echo '   (2 = yes. SECURITY DEFINER runs as owner and bypasses RLS, which is'
\echo '    why the signup trigger works while direct user INSERT is denied.)'

\echo ''
\echo '=== F. is search_path pinned on both SECURITY DEFINER functions? ==='
SELECT '   ' || p.proname || ' -> ' || coalesce(array_to_string(p.proconfig, ','), 'NOT PINNED') AS r
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public' AND p.prosecdef
 ORDER BY p.proname;
\echo '   (both must show search_path=public, pg_temp)'
