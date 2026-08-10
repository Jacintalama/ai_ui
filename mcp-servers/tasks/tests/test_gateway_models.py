"""The gateway models must match the migration, and the migration must be
re-runnable: db.py applies every migrations/*.sql on every single startup.
"""
import pathlib
import re

from models import GatewayLink, GatewayPairingCode, GatewaySession

MIGRATION = (
    pathlib.Path(__file__).parent.parent / "migrations" / "033_gateway.sql"
).read_text(encoding="utf-8")


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
    expected = {
        GatewayLink: {"id", "platform", "platform_user_id", "owui_user_id",
                      "email", "linked_at"},
        GatewayPairingCode: {"id", "code_hash", "platform", "platform_user_id",
                             "platform_user_name", "created_at", "expires_at",
                             "redeemed_at", "attempts"},
        GatewaySession: {"id", "platform", "chat_id", "owui_chat_id",
                         "owui_user_id", "updated_at"},
    }
    for model, columns in expected.items():
        assert {c.name for c in model.__table__.columns} == columns


def test_one_link_per_platform_user():
    # Two rows for the same Telegram account would make identity ambiguous and
    # the winner would depend on row order.
    assert "gateway_links_platform_user" in MIGRATION
