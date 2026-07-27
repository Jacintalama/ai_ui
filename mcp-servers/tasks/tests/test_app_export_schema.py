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
