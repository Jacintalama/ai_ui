# Built apps with admins and regular users

Date: 2026-07-30
Status: Approved direction (Jacint, 2026-07-30). Recipe proven against a real
Postgres before writing this — see Evidence.

Origin: Lukas, standup 2026-07-30: *"they have created logged in users and then
they can have admins ... I bet the builder then knows how to create admins and
regular users."*

## What is true today

His bet is half right. Measured in `claude_executor.py` and `templates.py`:

| Capability | Supported? |
|---|---|
| Sign up / sign in / sign out | **Yes** — the prompt teaches `signUp`, `signInWithPassword`, `signOut`, `onAuthStateChange` (`claude_executor.py:249`) |
| Each user sees only their own rows | **Yes** — `auth.uid() = user_id` policy (`:302`) |
| Admin vs regular roles | **No.** Zero notion of it anywhere in the builder |

The RLS section currently offers exactly two policy shapes: `allow_all_anon` for
no-auth apps, and `user_owns_row` for authed apps. There is no third shape for
"admin sees everything".

**Exposure note, and why this is safe to ship now:** `tasks.project_supabase`
has **0 rows** — no app has ever linked a database, so no app has ever had a
real login. This changes what the builder *can* produce; it does not touch
existing data.

## Why "just add it to the prompt" is not enough

This repo's most expensive lesson is that a prompt is not a guarantee. The git
commit, RLS, and `schema.sql` were all prompt-only; all three were broken in
production, one of them silently for 43 of 47 apps. Adding a fourth prompt-only
feature that governs **security** would repeat that exactly.

Two things follow:

1. The recipe itself must be **proven to work** before we teach it, not assumed.
   Done — see Evidence.
2. Verifying that a *built app* actually applied it is a separate, gated piece.
   It cannot be exercised while zero projects have a database, so it is
   deliberately out of scope here (see Out of scope).

## The recipe (proven, teach verbatim)

Three moving parts. The `SECURITY DEFINER` function is the load-bearing one: a
policy on `profiles` that queried `profiles` directly would recurse, and that is
the mistake an unguided model makes.

```sql
-- 1. who is who
CREATE TABLE profiles (
  id    uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text,
  role  text NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user'))
);
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- 2. the role check. SECURITY DEFINER runs as the owner so it does NOT
--    re-enter RLS (no recursion). search_path pinned so it cannot be hijacked.
CREATE FUNCTION public.is_admin() RETURNS boolean
  LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public, pg_temp AS
$$ SELECT EXISTS (
     SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin'
   ) $$;

CREATE POLICY profiles_read_self_or_admin ON profiles
  FOR SELECT TO authenticated USING (id = auth.uid() OR public.is_admin());

-- admins can appoint other admins; regular users cannot (proven)
CREATE POLICY profiles_admin_manages ON profiles
  FOR UPDATE TO authenticated
  USING (public.is_admin()) WITH CHECK (public.is_admin());

-- 3. every app table: owner OR admin
ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;
CREATE POLICY <name>_owner_or_admin ON <name>
  FOR ALL TO authenticated
  USING (user_id = auth.uid() OR public.is_admin())
  WITH CHECK (user_id = auth.uid() OR public.is_admin());

-- bootstrap: FIRST person to sign up becomes admin, everyone after is a user
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
```

**Why the trigger:** at build time no user exists, so "who is the admin?" has no
answer. First-signup-wins is self-bootstrapping — no dashboard visit, no service
key in the browser, no manual step. The person who builds the app signs in first
and is the admin.

## Evidence (run before this spec was written)

Executed against a real Postgres in a **throwaway `roles_probe` database** (prod
`openwebui` untouched), with the two Supabase pieces a plain Postgres lacks
shimmed in: an `auth` schema whose `auth.uid()` reads the JWT sub, and an
`authenticated` role. Tables created as owner, then `SET ROLE authenticated` so
RLS actually applies. **0 SQL errors.**

```
boss@example.com  -> admin              first signup becomes admin
staff@example.com -> user               second becomes a regular user
admin sees 2 of 2 rows                  want 2   PASS
staff sees 1 of 2 rows                  want 1   PASS
staff sees only its own: true                    PASS
staff reading profiles: 1 row                    PASS  (no recursion)
admin reading profiles: 2 rows                   PASS
staff self-promote attempt -> 'user'             PASS  (blocked)
admin promotes staff       -> 'admin'            PASS
```

Two findings that shaped the recipe:

- Without an UPDATE policy, RLS default-deny blocks role changes for
  *everyone*, admins included. So only the first signup could ever be admin —
  a dead end. Hence `profiles_admin_manages`.
- `SECURITY DEFINER` is required, not stylistic. Without it the `profiles`
  policy recurses.

Scripts kept at
`docs/superpowers/scripts/2026-07-30-prove-roles-recipe.sql` and
`docs/superpowers/scripts/2026-07-30-prove-admin-update.sql`.

## Changes

Prompt text only. No new Python, no new routes, no migration.

**One file: `claude_executor.py`**, inside `SUPABASE_SQL_TOOL_TEMPLATE` (the
`### RLS is MANDATORY` block, `:289-306`). Add a third policy shape
(admin-or-owner) beside the existing two, plus the roles recipe above. Trigger
it on the app's brief implying more than one kind of user ("admin", "staff",
"manage users", "moderator", "roles").

**CORRECTED while planning — `templates.py` is deliberately NOT touched.** The
first draft of this spec said to mirror the guidance there. Reading the file
shows that would be wrong: there is no shared Supabase constant. Each template
carries its own inline `SUPABASE SCHEMA` string (20 of them, `_RULES_DASHBOARD`,
`_RULES_CRUD`, `_RULES_CRM`, ...), and the only shared constant, `_BASE_RULES` /
`UNIVERSAL_RULES` (`:44`, `:153`), is about tech stack and layout — SQL policy
text does not belong there. Mirroring would mean duplicating the recipe up to 20
times.

`SUPABASE_SQL_TOOL_TEMPLATE` is already appended for every build where the SQL
tool is available, whatever the template, so one copy reaches all of them. The
per-template hints already say things like "RLS scoped to `auth.uid() = user_id`
if multi-user implied"; the shared recipe is what tells the agent *how* to do
that.

Deliberately keeps the existing two shapes unchanged — an app with one kind of
user should not pay for a `profiles` table it does not need.

## Testing

Unit, no network and no LLM:

- the prompt contains the admin-or-owner policy, `is_admin()`, the trigger, and
  `SECURITY DEFINER`
- it still contains the two pre-existing shapes (`allow_all_anon`,
  `user_owns_row`) — this must be additive
- the roles block appears only when the SQL tool is available, i.e. it lives
  inside the block gated behind `sql_tool_available` like the rest of that
  section
- the recipe's SQL is a single coherent unit: the policy references
  `public.is_admin()`, the function is defined before any policy that calls it,
  and every `CREATE TABLE` in the recipe is followed by `ENABLE ROW LEVEL
  SECURITY` (guards against a future edit dropping a piece)

The end-to-end proof of the SQL itself stays as the two checked-in scripts,
re-runnable on demand against a throwaway database. Deliberately NOT wired into
the automated suite: it needs a scratch database plus the `auth`/`authenticated`
shims, so it would only ever run in the container tier, and the setup cost
outweighs the protection when the recipe is a static block of text that the
prompt-content tests above already pin.

## Out of scope, stated plainly

- **Verifying a built app actually applied roles.** The machinery mostly exists:
  `app_export.build_schema_sql` already introspects `pg_class.relrowsecurity`
  and `pg_policies` and reports RLS as fact. Wiring that into a post-build check
  is the natural next piece, but it cannot be exercised end to end while
  `tasks.project_supabase` has 0 rows. Gate it on the first real link.
- **A built app was not observed doing this.** With no Supabase link, a real
  build never receives the SQL-tool block at all. The claim this spec supports
  is "the recipe is correct and the builder is told it" — not "an app was seen
  enforcing it".
- Roles beyond two, per-app custom role names, invite flows, admin UI.
