"""Prove an exported schema.sql for a ROLES app actually replays.

The unit tests in tests/test_app_export_functions.py assert the dump *contains*
the right statements in the right order. They cannot prove Postgres accepts it.
This does: it builds a real roles app in one throwaway database, exports it with
the real `app_export.build_schema_sql`, replays the result into a second empty
database, and then checks the security still behaves.

Before the 2026-08-03 fix this script fails at REPLAY with
`function is_admin() does not exist`, which is exactly the bug.

Run inside the tasks container (it has app_export + asyncpg):
    docker exec tasks python /tmp/2026-08-03-prove-export-replays.py

Safety: creates and drops two databases whose names contain "test". Never
touches `openwebui`; asserts that before doing anything.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

import asyncpg  # noqa: E402
from app_export import build_schema_sql  # noqa: E402

ADMIN_DSN = os.environ.get(
    "PROBE_ADMIN_DSN",
    "postgresql://openwebui:{}@postgres:5432/postgres".format(
        os.environ.get("POSTGRES_PASSWORD", "openwebui-secret")),
)
SRC = "export_test_src"
DST = "export_test_dst"

# The recipe the builder is told to emit, verbatim from
# claude_executor.py SUPABASE_SQL_TOOL_TEMPLATE.
RECIPE = [
    "CREATE TABLE profiles (id uuid PRIMARY KEY, email text, role text NOT NULL "
    "DEFAULT 'user' CHECK (role IN ('admin', 'user')))",
    "ALTER TABLE profiles ENABLE ROW LEVEL SECURITY",
    "CREATE FUNCTION public.is_admin() RETURNS boolean LANGUAGE sql SECURITY "
    "DEFINER STABLE SET search_path = public, pg_temp AS $$ SELECT EXISTS "
    "(SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin') $$",
    "CREATE POLICY profiles_read_self_or_admin ON profiles FOR SELECT TO "
    "authenticated USING (id = auth.uid() OR public.is_admin())",
    "CREATE POLICY profiles_admin_manages ON profiles FOR UPDATE TO authenticated "
    "USING (public.is_admin()) WITH CHECK (public.is_admin())",
    "CREATE FUNCTION public.guard_role_change() RETURNS trigger LANGUAGE plpgsql "
    "SECURITY DEFINER SET search_path = public, pg_temp AS $$ BEGIN IF NEW.role "
    "IS DISTINCT FROM OLD.role AND NOT public.is_admin() THEN RAISE EXCEPTION "
    "'only an admin can change a role'; END IF; RETURN NEW; END $$",
    "CREATE TRIGGER profiles_guard_role BEFORE UPDATE ON profiles FOR EACH ROW "
    "EXECUTE FUNCTION public.guard_role_change()",
    "CREATE TABLE items (id bigserial PRIMARY KEY, title text)",
    "ALTER TABLE items ADD COLUMN user_id uuid NOT NULL DEFAULT auth.uid()",
    "ALTER TABLE items ENABLE ROW LEVEL SECURITY",
    "CREATE POLICY items_owner_or_admin ON items FOR ALL TO authenticated "
    "USING (user_id = auth.uid() OR public.is_admin()) "
    "WITH CHECK (user_id = auth.uid() OR public.is_admin())",
]

# Supabase gives every project an auth schema and an authenticated role; a bare
# Postgres does not. Both databases get the same shims so the comparison is fair.
SHIMS = [
    "CREATE SCHEMA IF NOT EXISTS auth",
    "CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text)",
    "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS "
    "$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
    "'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; END $$",
]

PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")


async def reset(admin):
    for db in (SRC, DST):
        assert "test" in db, "refusing to touch a database without 'test' in its name"
        await admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {db}")


async def main():
    admin = await asyncpg.connect(ADMIN_DSN)
    db_now = await admin.fetchval("SELECT current_database()")
    assert db_now != "openwebui", f"connected to {db_now}; refusing to continue"
    await reset(admin)
    base = ADMIN_DSN.rsplit("/", 1)[0]

    src = await asyncpg.connect(f"{base}/{SRC}")
    dst = await asyncpg.connect(f"{base}/{DST}")
    try:
        print("\n=== 1. build a real roles app in the source database ===")
        for stmt in SHIMS + RECIPE:
            await src.execute(stmt)
        print("  applied the roles recipe, 0 errors")

        print("\n=== 2. export it with the REAL build_schema_sql ===")
        async def run_sql(sql):
            return [dict(r) for r in await src.fetch(sql)]
        schema_sql = await build_schema_sql(run_sql)
        check("dump defines is_admin()", "FUNCTION public.is_admin()" in schema_sql)
        check("dump defines guard_role_change()",
              "FUNCTION public.guard_role_change()" in schema_sql)
        check("dump carries the guard trigger",
              "CREATE TRIGGER profiles_guard_role" in schema_sql)
        check("dump did not silently omit anything",
              "could not be read" not in schema_sql.lower())

        print("\n=== 3. replay it into an EMPTY database ===")
        for stmt in SHIMS:
            await dst.execute(stmt)
        try:
            await dst.execute(schema_sql)
            check("schema.sql replays with 0 errors", True)
        except Exception as exc:
            check("schema.sql replays with 0 errors", False, f"{type(exc).__name__}: {exc}")
            print("\n----- generated schema.sql -----")
            print(schema_sql)
            raise SystemExit(1)

        print("\n=== 4. the restored database really enforces the roles ===")
        fn = await dst.fetchval(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname='public' "
            "AND p.proname IN ('is_admin','guard_role_change')")
        check("both functions exist after restore", fn == 2, f"found {fn} of 2")

        tg = await dst.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal")
        check("the trigger exists after restore", tg >= 1, f"found {tg}")

        pol = await dst.fetchval(
            "SELECT count(*) FROM pg_policies WHERE schemaname='public'")
        check("policies exist after restore", pol == 3, f"found {pol} of 3")

        rls = await dst.fetchval(
            "SELECT bool_and(c.relrowsecurity) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'")
        check("RLS is on for every table after restore", rls is True)

        # Behaviour, not just presence: an admin must see everything and a
        # regular user only their own row.
        await dst.execute(
            "INSERT INTO auth.users (id,email) VALUES "
            "('11111111-1111-1111-1111-111111111111','boss@example.com'),"
            "('22222222-2222-2222-2222-222222222222','staff@example.com')")
        await dst.execute(
            "INSERT INTO profiles (id,email,role) VALUES "
            "('11111111-1111-1111-1111-111111111111','boss@example.com','admin'),"
            "('22222222-2222-2222-2222-222222222222','staff@example.com','user')")
        await dst.execute(
            "GRANT USAGE ON SCHEMA public, auth TO authenticated; "
            "GRANT SELECT,INSERT,UPDATE,DELETE ON profiles, items TO authenticated; "
            "GRANT USAGE,SELECT ON SEQUENCE items_id_seq TO authenticated; "
            "GRANT EXECUTE ON FUNCTION public.is_admin(), auth.uid() TO authenticated")
        await dst.execute(
            "INSERT INTO items (title,user_id) VALUES "
            "('admin item','11111111-1111-1111-1111-111111111111'),"
            "('staff item','22222222-2222-2222-2222-222222222222')")

        async def as_user(uid, sql):
            await dst.execute("SET ROLE authenticated")
            await dst.execute(
                "SELECT set_config('request.jwt.claim.sub',$1,false)", uid)
            try:
                return await dst.fetchval(sql)
            finally:
                await dst.execute("RESET ROLE")

        admin_sees = await as_user("11111111-1111-1111-1111-111111111111",
                                   "SELECT count(*) FROM items")
        staff_sees = await as_user("22222222-2222-2222-2222-222222222222",
                                   "SELECT count(*) FROM items")
        check("restored admin sees all rows", admin_sees == 2, f"saw {admin_sees} of 2")
        check("restored regular user sees only their own", staff_sees == 1,
              f"saw {staff_sees}, wanted 1")

        # Self-promotion, twice over.
        #
        # First with the policies exactly as exported. RLS filters the UPDATE
        # to zero rows, so nothing is raised and nothing changes. Asserting on
        # an exception here would be wrong — the outcome that matters is the
        # role, not whether Postgres complained.
        async def try_promote():
            await dst.execute("SET ROLE authenticated")
            await dst.execute("SELECT set_config('request.jwt.claim.sub',"
                              "'22222222-2222-2222-2222-222222222222',false)")
            raised = ""
            try:
                await dst.execute(
                    "UPDATE profiles SET role='admin' WHERE id=auth.uid()")
            except Exception as exc:
                raised = str(exc)
            finally:
                await dst.execute("RESET ROLE")
            role = await dst.fetchval(
                "SELECT role FROM profiles WHERE email='staff@example.com'")
            return raised, role

        _, role_now = await try_promote()
        check("restored app blocks self-promotion (RLS)", role_now == "user",
              f"role is now {role_now!r}")

        # Now the case the guard trigger exists for. If a later edit adds a
        # permissive "users may update their own profile" policy, RLS stops
        # filtering and only the trigger stands between a regular user and
        # admin. This is the piece the exporter used to drop entirely, so a
        # restored app looked fine until someone added that policy.
        await dst.execute(
            "CREATE POLICY profiles_update_own ON profiles FOR UPDATE TO "
            "authenticated USING (id = auth.uid()) WITH CHECK (id = auth.uid())")
        raised, role_now = await try_promote()
        check("restored guard trigger blocks escalation once a permissive "
              "policy exists",
              role_now == "user" and "only an admin can change a role" in raised,
              f"role={role_now!r} raised={raised[:80]!r}")

        print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
        if FAIL:
            for f in FAIL:
                print("  FAILED:", f)
            raise SystemExit(1)
        print("The exported schema.sql replays and the restored app is secure.")
    finally:
        await src.close()
        await dst.close()
        for db in (SRC, DST):
            await admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        await admin.close()
        print("cleaned up both throwaway databases")


asyncio.run(main())
