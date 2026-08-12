"""The bots table is where a user's own bot token lives.

Column-level test on purpose: the encrypted token and the owner email are the
two fields whose absence would silently turn this into a plaintext store or a
shared one.
"""
from models import GatewayBot


def test_table_is_in_the_tasks_schema():
    assert GatewayBot.__tablename__ == "gateway_bots"
    assert GatewayBot.__table_args__["schema"] == "tasks"


def test_every_column_the_design_needs_exists():
    columns = set(GatewayBot.__table__.columns.keys())
    assert columns == {
        "id", "bot_key", "email", "platform", "token_encrypted",
        "webhook_secret", "bot_username", "allowed_ids",
        "owner_platform_user_id", "enabled", "created_at", "last_error",
    }


def test_the_token_column_is_named_for_being_encrypted():
    # A column called `token` would invite a plaintext write. The name is the
    # guardrail.
    assert "token" not in GatewayBot.__table__.columns
    assert "token_encrypted" in GatewayBot.__table__.columns


def test_a_bot_key_is_unique_across_users():
    # bot_key is the public path segment. Two rows sharing one would make an
    # inbound update ambiguous.
    assert GatewayBot.__table__.columns["bot_key"].unique is True
