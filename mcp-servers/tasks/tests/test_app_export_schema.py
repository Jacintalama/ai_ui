"""schema.sql must come from the LIVE database, never from the agent's claim.
RLS state is part of the dump, reported as fact (on AND off)."""
import app_export


def _runner(by_query):
    async def run_sql(sql: str):
        for key, rows in by_query.items():
            if key in sql:
                return rows
        return []
    return run_sql


CANNED = {
    "information_schema.columns": [
        {"table_name": "todos", "column_name": "id", "data_type": "bigint",
         "is_nullable": "NO", "column_default": None},
        {"table_name": "todos", "column_name": "title", "data_type": "text",
         "is_nullable": "YES", "column_default": "'untitled'::text"},
    ],
    "relrowsecurity": [
        {"relname": "todos", "relrowsecurity": True},
    ],
    "pg_policies": [
        {"tablename": "todos", "policyname": "allow_all_anon", "cmd": "ALL",
         "roles": ["anon"], "qual": "true", "with_check": "true"},
    ],
}


async def test_dump_contains_create_table_with_columns():
    sql = await app_export.build_schema_sql(_runner(CANNED))
    assert 'CREATE TABLE "todos"' in sql
    assert '"id" bigint NOT NULL' in sql
    assert '"title" text DEFAULT \'untitled\'::text' in sql


async def test_dump_reports_rls_enabled_with_policy():
    sql = await app_export.build_schema_sql(_runner(CANNED))
    assert 'ALTER TABLE "todos" ENABLE ROW LEVEL SECURITY;' in sql
    assert 'CREATE POLICY "allow_all_anon" ON "todos" FOR ALL TO anon USING (true) WITH CHECK (true);' in sql


async def test_dump_flags_rls_off_as_fact():
    canned = dict(CANNED)
    canned["relrowsecurity"] = [{"relname": "todos", "relrowsecurity": False}]
    canned["pg_policies"] = []
    sql = await app_export.build_schema_sql(_runner(canned))
    assert "RLS is NOT enabled" in sql
    assert "ENABLE ROW LEVEL SECURITY" not in sql.replace(
        "-- ALTER TABLE", "")  # only the suggestion comment, never a live stmt


async def test_empty_database_yields_honest_header():
    sql = await app_export.build_schema_sql(_runner({}))
    assert "no tables found" in sql.lower()


SERIAL = {
    "information_schema.columns": [
        {"table_name": "items", "column_name": "id", "data_type": "bigint",
         "is_nullable": "NO",
         "column_default": "nextval('items_id_seq'::regclass)"},
        {"table_name": "items", "column_name": "hits", "data_type": "integer",
         "is_nullable": "NO",
         "column_default": "nextval('items_hits_seq'::regclass)"},
        {"table_name": "items", "column_name": "title", "data_type": "text",
         "is_nullable": "YES", "column_default": None},
    ],
    "relrowsecurity": [{"relname": "items", "relrowsecurity": True}],
    "pg_policies": [],
}


async def test_serial_columns_do_not_reference_a_sequence_that_is_never_created():
    """Found by docs/superpowers/scripts/2026-08-03-prove-export-replays.py
    replaying a real dump: `bigserial` introspects as
    `bigint DEFAULT nextval('items_id_seq'::regclass)`, and nothing ever
    emitted CREATE SEQUENCE, so the restore died with

        UndefinedTableError: relation "items_id_seq" does not exist

    on the very first statement. That hits every app with an auto-increment
    id, not only the roles apps. Emitting the serial type instead makes
    Postgres create the sequence itself."""
    sql = await app_export.build_schema_sql(_runner(SERIAL))
    assert "nextval" not in sql, (
        "a nextval default names a sequence the dump never creates"
    )
    assert '"id" bigserial' in sql
    assert '"hits" serial' in sql
    assert '"title" text' in sql, "ordinary columns must be untouched"


async def test_serial_column_keeps_its_not_null():
    sql = await app_export.build_schema_sql(_runner(SERIAL))
    assert '"id" bigserial NOT NULL' in sql


async def test_ordinary_defaults_are_still_preserved():
    sql = await app_export.build_schema_sql(_runner(CANNED))
    assert '"title" text DEFAULT \'untitled\'::text' in sql


async def test_views_are_skipped_not_faked_as_tables():
    """information_schema.columns includes VIEWS; pg_class relkind='r' does
    not. A view must never render as CREATE TABLE with a bogus RLS warning."""
    canned = {
        "information_schema.columns": [
            {"table_name": "todos", "column_name": "id", "data_type": "bigint",
             "is_nullable": "NO", "column_default": None},
            {"table_name": "todos_view", "column_name": "id", "data_type": "bigint",
             "is_nullable": "YES", "column_default": None},
        ],
        "relrowsecurity": [{"relname": "todos", "relrowsecurity": True}],
        "pg_policies": [],
    }
    sql = await app_export.build_schema_sql(_runner(canned))
    assert 'CREATE TABLE "todos"' in sql
    assert 'CREATE TABLE "todos_view"' not in sql
    assert '"todos_view"' in sql  # disclosed as skipped, not silently dropped
    assert "RLS is NOT enabled" not in sql  # the view must not trigger the warning
