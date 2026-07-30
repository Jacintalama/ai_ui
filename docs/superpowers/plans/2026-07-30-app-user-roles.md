# Built-app admin/regular roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the App Builder to generate apps where an admin sees every row and a regular user sees only their own, using a recipe already proven against a real Postgres.

**Architecture:** Prompt text only. One block appended to `SUPABASE_SQL_TOOL_TEMPLATE` in `claude_executor.py`, which is already injected for every build where the SQL tool is available. No Python logic, no routes, no migration, no change to `templates.py`.

**Tech Stack:** Python 3.11, pytest (`asyncio_mode = auto`), Supabase Postgres RLS.

Spec: `docs/superpowers/specs/2026-07-30-app-user-roles-design.md`
Proof: `docs/superpowers/scripts/2026-07-30-prove-roles-recipe.sql`, `docs/superpowers/scripts/2026-07-30-prove-admin-update.sql`

---

### Task 1: Pin the two existing policy shapes before changing anything

The change must be purely additive. These tests must pass BEFORE the new text is
written, so a regression is visible immediately.

**Files:**
- Test: `mcp-servers/tasks/tests/test_supabase_prompt.py` (append)

- [ ] **Step 1: Write the tests**

Append to `mcp-servers/tasks/tests/test_supabase_prompt.py`:

```python


# --- roles: the change must be ADDITIVE ------------------------------------
# Lukas, standup 2026-07-30: "they can have admins ... I bet the builder then
# knows how to create admins and regular users." It did not - the RLS block
# offered exactly two policy shapes and neither covered "admin sees all".
# These two tests pin the pre-existing shapes so adding a third cannot quietly
# drop them.

def _sql_prompt() -> str:
    """The build prompt WITH the SQL tool block (OAuth-linked project)."""
    return build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-07-30",
        supabase_url="https://demo.supabase.co",
        has_db_uri=ce.sql_tool_available(
            db_uri=False, oauth_token=True, project_ref=True),
    )


def test_no_auth_policy_shape_survives():
    assert "allow_all_anon" in _sql_prompt()


def test_single_user_policy_shape_survives():
    assert "user_owns_row" in _sql_prompt()
```

- [ ] **Step 2: Run them and confirm they PASS**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_supabase_prompt.py -q -p no:cacheprovider -k "survives"
```

Expected: `2 passed`. These describe existing behaviour, so passing now is
correct — they are the regression net, not the red test.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_supabase_prompt.py
git commit -m "test(app-builder): pin the two existing RLS policy shapes before adding roles"
```

---

### Task 2: Red — assert the roles recipe is taught

**Files:**
- Test: `mcp-servers/tasks/tests/test_supabase_prompt.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_supabase_prompt.py`:

```python


def test_admin_or_owner_policy_shape_is_taught():
    """The third shape: admin sees all, owner sees own."""
    text = _sql_prompt()
    assert "public.is_admin()" in text
    assert "user_id = auth.uid() OR public.is_admin()" in text


def test_is_admin_is_security_definer():
    """Load-bearing, not stylistic: without SECURITY DEFINER a policy on
    profiles that queries profiles recurses. Proven in the recipe scripts."""
    text = _sql_prompt()
    assert "SECURITY DEFINER" in text
    assert "search_path = public, pg_temp" in text


def test_first_signup_becomes_admin_trigger_is_taught():
    """At build time no user exists, so 'who is the admin' has no answer.
    First-signup-wins bootstraps it with no manual step."""
    text = _sql_prompt()
    assert "on_auth_user_created" in text
    assert "handle_new_user" in text


def test_admins_can_appoint_admins():
    """Without an UPDATE policy, RLS default-deny blocks role changes for
    EVERYONE including admins, so only the first signup could ever be admin.
    Found by running the recipe, not by reading it."""
    text = _sql_prompt()
    assert "profiles_admin_manages" in text
    assert "FOR UPDATE TO authenticated" in text


def test_roles_recipe_is_gated_behind_the_sql_tool():
    """No SQL tool means the agent cannot create tables at all, so the recipe
    must not appear and waste context."""
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-07-30",
        supabase_url="https://demo.supabase.co",
        has_db_uri=False,
    )
    assert "public.is_admin()" not in text
    assert "on_auth_user_created" not in text


def test_recipe_defines_is_admin_before_any_policy_uses_it():
    """Order matters: a policy referencing is_admin() before the function
    exists fails at execution. Guards a future edit reordering the block."""
    text = _sql_prompt()
    definition = text.index("CREATE FUNCTION public.is_admin()")
    first_use = text.index("public.is_admin())")
    assert definition < first_use


def test_every_create_table_in_the_recipe_enables_rls():
    """A future edit must not add a table to the recipe without RLS."""
    text = _sql_prompt()
    assert text.count("CREATE TABLE profiles") == 1
    assert "ALTER TABLE profiles ENABLE ROW LEVEL SECURITY" in text
```

- [ ] **Step 2: Run them and confirm they FAIL for the right reason**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_supabase_prompt.py -q -p no:cacheprovider -k "admin or roles_recipe or first_signup or recipe_defines or every_create_table"
```

Expected: failures on the `assert ... in text` lines (the text is absent), and
`test_roles_recipe_is_gated_behind_the_sql_tool` PASSES already (nothing to
find yet). Do NOT proceed if a failure is an `AttributeError` or `TypeError` —
that means the helper is wrong, not the feature missing.

- [ ] **Step 3: Commit the red tests**

```bash
git add mcp-servers/tasks/tests/test_supabase_prompt.py
git commit -m "test(app-builder): red tests for the admin/regular roles recipe"
```

---

### Task 3: Green — add the roles recipe to the prompt

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py:303-306` (end of `SUPABASE_SQL_TOOL_TEMPLATE`)

- [ ] **Step 1: Read the current end of the block to anchor the edit**

```bash
cd mcp-servers/tasks
sed -n '289,306p' claude_executor.py
```

Expected: the `### RLS is MANDATORY on every table you create` heading, the
three numbered steps with `allow_all_anon` and `user_owns_row`, then
`Pick the policy that matches the app's auth model. Apply all three steps for
every new table — no exceptions.` and the closing `"""`.

- [ ] **Step 2: Insert the roles section before the closing `"""`**

Replace exactly this text:

```
Pick the policy that matches the app's auth model. Apply all three steps for
every new table — no exceptions.
"""
```

with:

```
Pick the policy that matches the app's auth model. Apply all three steps for
every new table — no exceptions.

### Two kinds of user: admins and regular users

Use this ONLY when the brief implies more than one kind of user — words like
admin, staff, manage users, moderator, roles. A single-user app must not pay
for a `profiles` table it does not need; use `user_owns_row` above instead.

An admin sees every row. A regular user sees only their own. Emit these in
order, one statement per `/db/sql` call:

  1. Who is who:
     `CREATE TABLE profiles (id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, email text, role text NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')));`
  2. `ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;`
  3. The role check. SECURITY DEFINER is REQUIRED — it runs as the owner so it
     does not re-enter RLS. Without it, a policy on `profiles` that reads
     `profiles` recurses and every query fails:
     `CREATE FUNCTION public.is_admin() RETURNS boolean LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public, pg_temp AS $$ SELECT EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin') $$;`
  4. `CREATE POLICY profiles_read_self_or_admin ON profiles FOR SELECT TO authenticated USING (id = auth.uid() OR public.is_admin());`
  5. Admins appoint other admins. Without this UPDATE policy nobody can change
     a role at all — not even an admin — so only the very first signup could
     ever be one:
     `CREATE POLICY profiles_admin_manages ON profiles FOR UPDATE TO authenticated USING (public.is_admin()) WITH CHECK (public.is_admin());`
  6. Every other table gets a `user_id uuid NOT NULL DEFAULT auth.uid()` column
     and this policy instead of `user_owns_row`:
     `CREATE POLICY <table>_owner_or_admin ON <table> FOR ALL TO authenticated USING (user_id = auth.uid() OR public.is_admin()) WITH CHECK (user_id = auth.uid() OR public.is_admin());`
  7. Bootstrap. At build time there are no users, so the FIRST person to sign up
     becomes the admin and everyone after is a regular user. No manual step, no
     dashboard visit, no service key in the browser:
     `CREATE FUNCTION public.handle_new_user() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$ BEGIN INSERT INTO public.profiles (id, email, role) VALUES (NEW.id, NEW.email, CASE WHEN NOT EXISTS (SELECT 1 FROM public.profiles) THEN 'admin' ELSE 'user' END); RETURN NEW; END $$;`
  8. `CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();`

In the UI, read the signed-in user's role once after sign-in
(`select role from profiles where id = <uid>`) and show admin-only controls
behind it. Never trust a role held only in browser state for data access — the
policies above are what actually enforce it.
"""
```

- [ ] **Step 3: Run the roles tests and confirm they PASS**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_supabase_prompt.py -q -p no:cacheprovider
```

Expected: all tests pass, including the two additive-guard tests from Task 1.

- [ ] **Step 4: Confirm nothing else regressed**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_supabase_prompt.py tests/test_enhance_prompt.py tests/test_prebuild_questions.py -q -p no:cacheprovider
```

Expected: all pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/claude_executor.py
git commit -m "feat(app-builder): teach the builder admin and regular user roles"
```

---

### Task 4: Verify the taught SQL is the SQL that was proven

The prompt now contains SQL as text. If it drifted from the proven recipe by so
much as a typo, the agent emits something broken. Compare them.

**Files:**
- Test: `mcp-servers/tasks/tests/test_supabase_prompt.py` (append)

- [ ] **Step 1: Write the test**

```python


def test_taught_sql_matches_the_proven_recipe():
    """The recipe was proven against a real Postgres before being taught
    (docs/superpowers/scripts/2026-07-30-prove-roles-recipe.sql). If the prompt
    text drifts from what was proven, the agent emits untested SQL."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[3]
    proof = (repo / "docs" / "superpowers" / "scripts"
             / "2026-07-30-prove-roles-recipe.sql")
    if not proof.is_file():
        import pytest
        pytest.skip("proof script not present")
    proven = proof.read_text(encoding="utf-8")
    text = _sql_prompt()

    # Whitespace-normalised so line wrapping in either file is irrelevant.
    # The taught prompt is written to match the proof byte-for-byte on these
    # fragments, so no per-fragment special-casing is needed.
    norm_proven = " ".join(proven.split())
    norm_taught = " ".join(text.split())
    for fragment in (
        "SECURITY DEFINER",
        "search_path = public, pg_temp",
        "role IN ('admin', 'user')",
        "id = auth.uid() OR public.is_admin()",
        "user_id = auth.uid() OR public.is_admin()",
        "on_auth_user_created",
        "handle_new_user",
    ):
        norm_f = " ".join(fragment.split())
        assert norm_f in norm_proven, f"{fragment!r} is not in the PROVEN script"
        assert norm_f in norm_taught, f"{fragment!r} is not in the TAUGHT prompt"
```

- [ ] **Step 2: Run it**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_supabase_prompt.py -q -p no:cacheprovider -k "proven_recipe"
```

Expected: PASS. If it fails on "not in the TAUGHT prompt", the prompt text in
Task 3 was mistyped — fix the prompt, not the test.

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/tests/test_supabase_prompt.py
git commit -m "test(app-builder): the taught roles SQL matches the proven recipe"
```

---

### Task 5: Full suite, deploy, verify live

**Files:**
- Modify: none (deploy only)

- [ ] **Step 1: Full local suite**

```bash
cd mcp-servers/tasks
python -m pytest tests/ -q -p no:cacheprovider
```

Expected: passes up by the number of new tests; **error count unchanged at 132**.
Those 132 are the pre-existing DB tier (`ERROR at setup`, `asyncpg.connect`) —
there is no local Postgres. Any change in that number is your regression.

- [ ] **Step 2: Deploy the one changed source file plus the tests**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO"
scp mcp-servers/tasks/claude_executor.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/claude_executor.py
scp mcp-servers/tasks/tests/test_supabase_prompt.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/tests/test_supabase_prompt.py
ssh root@46.224.193.25 "cd /root/proxy-server && sed -i 's/\r$//' mcp-servers/tasks/claude_executor.py mcp-servers/tasks/tests/test_supabase_prompt.py && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

The `sed` is mandatory: this repo checks out CRLF on Windows.

- [ ] **Step 3: Verify in the container that the prompt really carries the recipe**

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -c \"
import claude_executor as ce
t = ce.build_prompt(description=\\\"x\\\", action_type=\\\"BUILD\\\", priority=\\\"IMPORTANT\\\", meeting_title=\\\"m\\\", meeting_date=\\\"2026-07-30\\\", supabase_url=\\\"https://demo.supabase.co\\\", has_db_uri=ce.sql_tool_available(db_uri=False, oauth_token=True, project_ref=True))
for k in (\\\"public.is_admin()\\\", \\\"SECURITY DEFINER\\\", \\\"on_auth_user_created\\\", \\\"profiles_admin_manages\\\", \\\"allow_all_anon\\\", \\\"user_owns_row\\\"):
    print(f\\\"  {k}: {k in t}\\\")
\"'"
```

Expected: all six `True`. The last two prove the change stayed additive.

- [ ] **Step 4: In-container tests and health**

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_supabase_prompt.py tests/test_app_regression.py -q -p no:cacheprovider | tail -2'"
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
```

Expected: tests pass; `{"status":"ok"}`.

- [ ] **Step 5: Re-run the SQL proof against a throwaway DB (optional but cheap)**

```bash
ssh root@46.224.193.25 "docker cp /root/proxy-server/docs/superpowers/scripts/2026-07-30-prove-roles-recipe.sql postgres:/tmp/r.sql && docker exec postgres psql -U openwebui -d postgres -q -c 'DROP DATABASE IF EXISTS roles_probe;' -c 'CREATE DATABASE roles_probe;' && docker exec postgres psql -U openwebui -d roles_probe -q -f /tmp/r.sql 2>&1 | grep -E '^ +(admin|staff|boss|rows|final)' ; docker exec postgres psql -U openwebui -d postgres -q -c 'DROP DATABASE roles_probe;'"
```

Expected: `admin sees 2 of 2`, `staff sees 1 of 2`, `staff sees only its own:
true`. **Never run this against `openwebui`.**

- [ ] **Step 6: Push and record the deploy**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO"
git fetch fork && git rebase fork/main && git push fork main
SHA=$(git rev-parse HEAD)
ssh root@46.224.193.25 "cd /root/proxy-server && echo '{\"sha\":\"'$SHA'\",\"deployed_at\":\"'$(date -Iseconds)'\",\"deployed_by\":\"claude@app-roles\"}' > .deploy-state"
```

Rebase before pushing: Ralph pushes to the same branch from another machine.
Never force-push. If compose was touched, re-grep the SERVER copy for his keys
(`VERCEL_`, `OPENAI_API_KEY`) — clobbering them has happened twice.

---

## What this plan does NOT claim

A built app was never observed enforcing roles, and cannot be until someone
links a Supabase project (`tasks.project_supabase` has 0 rows, so a real build
never receives the SQL-tool block). The claim is: **the recipe is proven correct
and the builder is now told it.** Say that plainly in any report; do not upgrade
it to "apps now have working admin roles".
