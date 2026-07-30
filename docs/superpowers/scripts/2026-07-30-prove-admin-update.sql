-- Completes the recipe: an admin can appoint another admin; a regular user cannot.
-- Runs against the roles_probe scratch DB, on top of prove_roles_recipe.sql.
\set ON_ERROR_STOP off

CREATE POLICY profiles_admin_manages ON profiles
  FOR UPDATE TO authenticated
  USING (public.is_admin()) WITH CHECK (public.is_admin());

SET ROLE authenticated;

\echo '=== regular user tries to promote itself (must FAIL) ==='
SELECT set_config('request.jwt.claim.sub', '22222222-2222-2222-2222-222222222222', false) \gset
UPDATE profiles SET role = 'admin' WHERE id = auth.uid();
SELECT '  staff role after SELF-promote attempt: ' || role AS r
  FROM profiles WHERE id = auth.uid();

\echo '=== admin promotes staff (must SUCCEED) ==='
SELECT set_config('request.jwt.claim.sub', '11111111-1111-1111-1111-111111111111', false) \gset
UPDATE profiles SET role = 'admin' WHERE email = 'staff@example.com';

RESET ROLE;
SELECT '  staff role after ADMIN promoted them: ' || role AS r
  FROM profiles WHERE email = 'staff@example.com';
