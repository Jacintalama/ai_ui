"""schema.sql must export FUNCTIONS and TRIGGERS, not just tables and policies.

Why: on 2026-07-30 the builder was taught an admin/regular-user roles recipe
whose security rests on `public.is_admin()` (a SECURITY DEFINER function), a
`guard_role_change()` trigger, and a `handle_new_user()` signup trigger. The
exporter read only information_schema.columns, pg_class and pg_policies, so an
exported schema.sql emitted

    CREATE POLICY "profiles_read_self_or_admin" ON "profiles" ... USING (... OR is_admin())

with no `is_admin()` anywhere in the file. Replaying it fails at that statement,
and the app silently loses its signup trigger — so the first user never becomes
an admin. "Take your app with you" broke for exactly the apps with the most
valuable schema.

Ordering is load-bearing and is asserted here:
  tables -> functions -> RLS/policies -> triggers
`is_admin()` is LANGUAGE sql, so Postgres validates its body at CREATE time and
it must come after `profiles`. Policies calling it must come after it.
"""
import app_export


def _runner(by_query, fail_on=()):
    async def run_sql(sql: str):
        for marker in fail_on:
            if marker in sql:
                raise RuntimeError(f"permission denied for {marker}")
        for key, rows in by_query.items():
            if key in sql:
                return rows
        return []
    return run_sql


IS_ADMIN_DEF = (
    "CREATE OR REPLACE FUNCTION public.is_admin()\n RETURNS boolean\n"
    " LANGUAGE sql\n SECURITY DEFINER\n STABLE\n"
    " SET search_path TO 'public', 'pg_temp'\nAS $function$ "
    "SELECT EXISTS (SELECT 1 FROM public.profiles "
    "WHERE id = auth.uid() AND role = 'admin') $function$"
)
HANDLE_NEW_USER_DEF = (
    "CREATE OR REPLACE FUNCTION public.handle_new_user()\n RETURNS trigger\n"
    " LANGUAGE plpgsql\n SECURITY DEFINER\nAS $function$ BEGIN "
    "INSERT INTO public.profiles (id, email, role) VALUES (NEW.id, NEW.email, "
    "'user') ON CONFLICT (id) DO NOTHING; RETURN NEW; END $function$"
)

ROLES_APP = {
    "information_schema.columns": [
        {"table_name": "profiles", "column_name": "id", "data_type": "uuid",
         "is_nullable": "NO", "column_default": None},
        {"table_name": "profiles", "column_name": "role", "data_type": "text",
         "is_nullable": "NO", "column_default": "'user'::text"},
    ],
    "relrowsecurity": [{"relname": "profiles", "relrowsecurity": True}],
    "pg_policies": [
        {"tablename": "profiles", "policyname": "profiles_read_self_or_admin",
         "cmd": "SELECT", "roles": ["authenticated"],
         "qual": "((id = auth.uid()) OR is_admin())", "with_check": None},
    ],
    "pg_proc": [
        {"name": "is_admin", "definition": IS_ADMIN_DEF},
        {"name": "handle_new_user", "definition": HANDLE_NEW_USER_DEF},
    ],
    "pg_trigger": [
        {"table_name": "profiles", "name": "profiles_guard_role",
         "definition": "CREATE TRIGGER profiles_guard_role BEFORE UPDATE ON "
                       "public.profiles FOR EACH ROW EXECUTE FUNCTION "
                       "public.guard_role_change()"},
        {"table_name": "users", "name": "on_auth_user_created",
         "definition": "CREATE TRIGGER on_auth_user_created AFTER INSERT ON "
                       "auth.users FOR EACH ROW EXECUTE FUNCTION "
                       "public.handle_new_user()"},
    ],
}


# ---------------------------------------------------------------------------
# The break itself.
# ---------------------------------------------------------------------------

async def test_function_a_policy_depends_on_is_exported():
    """The whole bug in one assertion: a policy calls is_admin(), so the dump
    must define is_admin()."""
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert "is_admin()" in sql, "policy references it, so it must be defined"
    assert "FUNCTION public.is_admin()" in sql
    assert "SECURITY DEFINER" in sql, (
        "SECURITY DEFINER is load-bearing: without it the profiles policy "
        "recurses. Exporting the function without it changes its meaning."
    )


async def test_signup_trigger_is_exported():
    """Without on_auth_user_created no profile row is ever created, so the
    first user never becomes admin and the app is unusable after restore."""
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert "CREATE TRIGGER on_auth_user_created" in sql
    assert "public.handle_new_user()" in sql


async def test_table_trigger_is_exported():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert "CREATE TRIGGER profiles_guard_role" in sql


# ---------------------------------------------------------------------------
# Ordering: the dump has to actually replay, not merely contain the pieces.
# ---------------------------------------------------------------------------

async def test_function_is_defined_before_the_policy_that_calls_it():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert sql.index("FUNCTION public.is_admin()") < sql.index("CREATE POLICY"), (
        "CREATE POLICY ... USING (is_admin()) fails if the function does not "
        "exist yet"
    )


async def test_table_is_created_before_the_function_that_reads_it():
    """is_admin() is LANGUAGE sql, so its body is validated at CREATE time and
    public.profiles must already exist."""
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert sql.index('CREATE TABLE "profiles"') < sql.index("FUNCTION public.is_admin()")


async def test_trigger_comes_after_its_function():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert sql.index("FUNCTION public.handle_new_user()") < sql.index(
        "CREATE TRIGGER on_auth_user_created")


async def test_every_statement_is_terminated():
    """A missing semicolon silently merges two statements."""
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    for line in sql.splitlines():
        s = line.strip()
        if s.startswith("CREATE TRIGGER"):
            assert s.endswith(";"), f"unterminated: {s[:60]}"


# ---------------------------------------------------------------------------
# Honesty when introspection is refused, rather than a silent gap.
# ---------------------------------------------------------------------------

async def test_function_read_failure_is_disclosed_not_swallowed():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP, fail_on=("pg_proc",)))
    assert "could not be read" in sql.lower()
    assert 'CREATE TABLE "profiles"' in sql, "the rest of the dump still works"


async def test_trigger_read_failure_is_disclosed_not_swallowed():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP, fail_on=("pg_trigger",)))
    assert "could not be read" in sql.lower()
    assert 'CREATE TABLE "profiles"' in sql


async def test_header_no_longer_claims_completeness_it_does_not_have():
    sql = await app_export.build_schema_sql(_runner(ROLES_APP))
    assert "functions" in sql.split("CREATE TABLE")[0].lower(), (
        "the header lists what the dump does and does not cover; now that "
        "functions are covered it must say so"
    )


# ---------------------------------------------------------------------------
# Apps with no functions must not regress or gain noise.
# ---------------------------------------------------------------------------

async def test_plain_app_is_unchanged_by_this_feature():
    plain = {
        "information_schema.columns": [
            {"table_name": "todos", "column_name": "id", "data_type": "bigint",
             "is_nullable": "NO", "column_default": None},
        ],
        "relrowsecurity": [{"relname": "todos", "relrowsecurity": True}],
        "pg_policies": [
            {"tablename": "todos", "policyname": "user_owns_row", "cmd": "ALL",
             "roles": ["authenticated"], "qual": "(user_id = auth.uid())",
             "with_check": "(user_id = auth.uid())"},
        ],
    }
    sql = await app_export.build_schema_sql(_runner(plain))
    assert 'CREATE TABLE "todos"' in sql
    assert 'ALTER TABLE "todos" ENABLE ROW LEVEL SECURITY;' in sql
    assert 'CREATE POLICY "user_owns_row"' in sql
    assert "CREATE TRIGGER" not in sql
    assert "could not be read" not in sql.lower()
