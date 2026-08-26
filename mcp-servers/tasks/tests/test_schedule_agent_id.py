"""A schedule can name one of the user's agents.

The column is nullable and null means today's behaviour, because every row
that already exists has one. `kind` is deliberately untouched: it is already
'agent' or 'video', where 'agent' means the CLI executor, and overloading that
word further would make the collision worse.
"""
import pathlib

from models import Schedule
from routes_schedules import CreateScheduleIn

MIGRATION = (pathlib.Path(__file__).resolve().parents[1]
             / "migrations" / "041_schedule_agent_id.sql")


def test_the_model_carries_an_agent_id():
    assert hasattr(Schedule, "agent_id")


def test_a_schedule_can_be_created_without_naming_an_agent():
    """Null is the normal case and must stay the default, or every existing
    caller would suddenly be required to pick one."""
    payload = CreateScheduleIn(name="n", cron_expr="0 9 * * *", prompt="p")
    assert payload.agent_id is None


def test_a_schedule_can_name_an_agent():
    payload = CreateScheduleIn(name="n", cron_expr="0 9 * * *", prompt="p",
                               agent_id="agent-triage-0002")
    assert payload.agent_id == "agent-triage-0002"


def test_the_migration_is_additive_and_idempotent():
    """db.py re-runs every migration on every startup, so a migration that is
    not idempotent takes the service down on the second boot."""
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists agent_id" in sql
    assert "drop" not in sql, "a migration on a live table must not drop anything"
    assert "not null" not in sql, "existing rows have no agent, so it must be nullable"


def test_the_migration_does_not_touch_kind():
    """kind already means the CLI executor, so this feature must not move it.

    Comments are stripped first: the migration explains at length WHY it is not
    a new kind, and a naive search would match that explanation and pass while
    the statements did something else entirely.
    """
    statements = "\n".join(
        line.split("--")[0]
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
    ).lower()
    assert "kind" not in statements, statements
