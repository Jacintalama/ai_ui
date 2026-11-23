"""GET /schedules/outputs: what a person's cron jobs answered, with the text.

The Cron Jobs list carries a run's text only when the run went wrong, to
keep the list small. The Cron Outputs page (/cronjobs/output) exists to
READ the answers, so it has its own route that returns them, scoped to one
person and capped.

The SQL runs against the real database only on the server; these pin the
pure parts and the statement itself.
"""
from datetime import datetime, timezone

import routes_schedules as R


def test_the_limit_has_a_default_a_floor_and_a_cap():
    assert R.outputs_limit(None) == R.OUTPUTS_DEFAULT
    assert R.outputs_limit(0) == 1
    assert R.outputs_limit(-5) == 1
    assert R.outputs_limit(10_000) == R.OUTPUTS_MAX
    assert R.outputs_limit("junk") == R.OUTPUTS_DEFAULT
    assert R.outputs_limit(7) == 7


def test_an_output_carries_the_whole_answer():
    t0 = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 24, 1, 1, tzinfo=timezone.utc)
    out = R.shape_output({"schedule_id": "abc", "name": "Inbox check",
                          "started_at": t0, "finished_at": t1,
                          "status": "completed", "result": "x" * 5000})
    assert out["name"] == "Inbox check"
    assert out["status"] == "completed" and out["ok"] is True
    assert out["at"] == t0.isoformat()
    assert len(out["result"]) == 5000, "the page is for reading the answer"


def test_a_run_that_never_finished_reads_as_failed():
    t0 = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
    out = R.shape_output({"schedule_id": "abc", "name": "x",
                          "started_at": t0, "finished_at": None,
                          "status": "running", "result": None})
    assert out["status"] == "failed" and out["ok"] is False
    assert out["result"] == ""


def test_the_statement_is_scoped_to_the_owner_newest_first_and_capped():
    sql = " ".join(R._OUTPUTS_SQL.split())
    assert "WHERE s.user_email = :email" in sql
    assert "JOIN tasks.schedules s ON s.id = r.schedule_id" in sql
    assert "ORDER BY r.started_at DESC" in sql
    assert "LIMIT :n" in sql


def test_the_route_is_registered_before_anything_that_takes_an_id():
    paths = [getattr(r, "path", "") for r in R.router.routes]
    assert "/schedules/outputs" in paths
