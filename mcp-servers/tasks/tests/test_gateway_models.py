"""The gateway models must match the migration, and the migration must be
re-runnable: db.py applies every migrations/*.sql on every single startup.

Column names are parsed from the migration SQL, not hand-listed, so a column
renamed in one place and not the other fails here instead of at runtime.
"""
import pathlib
import re

from models import GatewayLink, GatewayPairingCode, GatewaySession

MIGRATION = (
    pathlib.Path(__file__).parent.parent / "migrations" / "033_gateway.sql"
).read_text(encoding="utf-8")


def _sql_columns(table: str) -> set[str]:
    """Column names declared inside one CREATE TABLE block of the migration.

    Parsed rather than hand-listed. Two hand-maintained lists agreeing with each
    other proves nothing about the SQL that actually builds the table.
    """
    block = re.search(
        rf"CREATE TABLE IF NOT EXISTS tasks\.{table}\s*\((.*?)\n\);",
        MIGRATION, re.IGNORECASE | re.DOTALL)
    assert block, f"no CREATE TABLE block found for tasks.{table}"

    # Table-level constraints start with a keyword rather than a column name.
    keywords = {"primary", "unique", "foreign", "constraint", "check", "exclude"}
    names = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        first = line.split()[0]
        if first.lower() in keywords:
            continue
        names.add(first)
    return names


def test_every_create_is_idempotent():
    creates = re.findall(r"CREATE\s+(TABLE|INDEX|UNIQUE INDEX)\s+(?!IF NOT EXISTS)",
                         MIGRATION, re.IGNORECASE)
    assert creates == [], f"non-idempotent DDL would fail on the second boot: {creates}"


def test_all_three_tables_are_created():
    for table in ("gateway_links", "gateway_pairing_codes", "gateway_sessions"):
        assert f"tasks.{table}" in MIGRATION


def test_models_point_at_the_tasks_schema():
    for model in (GatewayLink, GatewayPairingCode, GatewaySession):
        assert model.__table_args__["schema"] == "tasks"


def test_model_columns_match_the_migration():
    # Parsed from the SQL, not hand-listed, so a column renamed in one place and
    # not the other fails here instead of at runtime against a real database.
    for model, table in ((GatewayLink, "gateway_links"),
                         (GatewayPairingCode, "gateway_pairing_codes"),
                         (GatewaySession, "gateway_sessions")):
        assert {c.name for c in model.__table__.columns} == _sql_columns(table)


def test_the_column_parser_actually_finds_columns():
    # Guards the test above: a parser that silently returned an empty set would
    # make it pass for any model at all.
    assert _sql_columns("gateway_links") == {
        "id", "platform", "platform_user_id", "owui_user_id", "email", "linked_at"}
    assert len(_sql_columns("gateway_pairing_codes")) == 9
    assert len(_sql_columns("gateway_sessions")) == 6


def test_one_link_per_platform_user():
    # Two rows for the same Telegram account would make identity ambiguous and
    # the winner would depend on row order.
    assert "gateway_links_platform_user" in MIGRATION
