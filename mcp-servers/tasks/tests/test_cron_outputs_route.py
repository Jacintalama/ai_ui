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


def _flat(sql):
    return " ".join(sql.split())


def test_the_statement_is_scoped_to_the_owner_newest_first_and_capped():
    for unread_only in (False, True):
        sql = _flat(R.outputs_sql(unread_only))
        assert "WHERE s.user_email = :email" in sql
        assert "JOIN tasks.schedules s ON s.id = r.schedule_id" in sql
        assert "ORDER BY r.started_at DESC" in sql
        assert "LIMIT :n" in sql
        assert "r.id" in sql and "r.unread" in sql
    assert "AND r.unread" in _flat(R.outputs_sql(True))
    assert "AND r.unread" not in _flat(R.outputs_sql(False))


def test_the_routes_are_all_there_and_nothing_else_went_missing():
    paths = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", []) or [])))
             for r in R.router.routes}
    names = {p for p, _ in paths}
    for p in ("/schedules/outputs", "/schedules/outputs/unread",
              "/schedules/outputs/{run_id}/read", "/schedules/outputs/read-all",
              # the routes the outputs work sits beside, which must survive it
              "/schedules", "/schedules/{schedule_id}",
              "/schedules/{schedule_id}/run-now",
              "/schedules/{schedule_id}/enable",
              "/schedules/{schedule_id}/disable"):
        assert p in names, p


# --- read and unread, like an email ------------------------------------------

def test_an_output_says_whether_it_is_unread_and_carries_its_id():
    out = R.shape_output({"id": "11111111-1111-1111-1111-111111111111",
                          "schedule_id": "abc", "name": "x",
                          "started_at": None, "finished_at": None,
                          "status": "completed", "result": "hi",
                          "unread": True})
    assert out["unread"] is True
    assert out["id"] == "11111111-1111-1111-1111-111111111111"


def test_the_unread_count_is_only_this_persons_and_only_unread():
    sql = _flat(R._UNREAD_COUNT_SQL)
    assert "WHERE s.user_email = :email AND r.unread" in sql


def test_marking_one_read_only_touches_the_owners_run():
    sql = _flat(R._MARK_ONE_SQL)
    assert "SET unread = :unread" in sql
    assert "WHERE id = CAST(:id AS UUID)" in sql
    assert "schedule_id IN (SELECT id FROM tasks.schedules WHERE user_email = :email)" in sql
    assert "RETURNING id" in sql, "so a run that is not theirs is a 404"


def test_mark_all_is_the_owners_and_can_be_one_cron():
    every = _flat(R.mark_all_sql(False))
    one = _flat(R.mark_all_sql(True))
    for sql in (every, one):
        assert "SET unread = false" in sql
        assert "WHERE user_email = :email" in sql
    assert "CAST(:schedule_id AS UUID)" in one
    assert ":schedule_id" not in every


def test_a_bad_id_never_reaches_the_database():
    assert R.valid_uuid("not-a-uuid") is None
    assert R.valid_uuid("") is None
    assert R.valid_uuid(None) is None
    assert R.valid_uuid("1' OR '1'='1") is None
    good = "11111111-1111-1111-1111-111111111111"
    assert R.valid_uuid(good) == good


def test_runs_from_before_the_inbox_read_as_read_and_new_ones_arrive_unread():
    import pathlib
    import inspect
    import scheduler
    mig = (pathlib.Path(R.__file__).parent / "migrations"
           / "072_schedule_run_unread.sql").read_text(encoding="utf-8")
    code = " ".join(l for l in mig.splitlines() if not l.strip().startswith("--"))
    assert "ADD COLUMN IF NOT EXISTS unread BOOLEAN NOT NULL DEFAULT false" in _flat(code)
    assert "UPDATE" not in code.upper(), "re-run on every start would re-read everything"
    insert = _flat(inspect.getsource(scheduler._record_run))
    assert "status, result, unread)" in insert
    assert ":result, :unread)" in insert
