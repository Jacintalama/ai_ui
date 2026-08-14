"""Per-user limits on schedule creation.

Each schedule spawns a Claude Code agent run (scheduler.py dispatches through
the remote executor), and concurrency is capped at 3 purely to avoid OOM on a
3.8GB box. Before this, create_schedule validated only that the cron expression
parsed — so `* * * * *`, an agent run every minute forever, was accepted. That
was survivable while the page was admin-only; opening it to everyone makes a cap
necessary rather than nice to have.

The helper is pure and uses a FIXED base time so the result is deterministic and
does not depend on when the suite runs.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()
os.environ.setdefault("CRON_SHARED_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from routes_schedules import min_interval_minutes  # noqa: E402


@pytest.mark.parametrize("expr,expected", [
    ("* * * * *", 1),        # every minute — the pathological case
    ("*/5 * * * *", 5),      # a step, not the literal every-minute
    ("*/15 * * * *", 15),    # exactly the boundary
    ("0,30 * * * *", 30),    # comma list
    ("0 * * * *", 60),       # hourly
    ("0 9 * * *", 1440),     # daily
])
def test_min_interval_is_the_smallest_gap(expr, expected):
    assert min_interval_minutes(expr) == expected


def test_uneven_schedules_report_their_SMALLEST_gap():
    """Mon and Tue at 09:00: gaps are 1 day, 6 days, 1 day. The smallest is
    what matters — an average would hide a burst."""
    assert min_interval_minutes("0 9 * * 1,2") == 1440


def test_a_garbage_expression_does_not_raise():
    """The caller validates with croniter.is_valid first, but this must never
    be the thing that 500s a request."""
    assert min_interval_minutes("not a cron") == 0.0


@pytest.mark.parametrize("expr", [
    "0,30,59 0,23 * * *",   # 23:59 -> next 00:00 is one minute apart
    "0,15,59 0,23 * * *",
])
def test_the_midnight_wrap_is_not_hidden_by_the_base_time(expr):
    """Four samples taken from midnight all land inside the same day, so the
    window closes before the 23:59 -> 00:00 wrap and these read as 29 and 15
    minutes. Both really fire one minute apart. A base late in the day sees the
    wrap in the very first gap, which is why the base time is 23:45 and not
    00:00 — with the same four samples."""
    assert min_interval_minutes(expr) == 1


def test_a_day_of_week_wrap_is_still_a_blind_spot():
    """KNOWN LIMIT, pinned so a future change to the base is deliberate.

    Sunday 23:59 -> Monday 00:00 is also one minute, but 2026-01-01 is a
    Thursday: the first matching fire is Sunday 00:00 and all four samples land
    on that Sunday, so the wrap is never sampled. Moving the base onto a Sunday
    fixes THIS expression and breaks Sunday-only ones (`0,15,59 * * * 0`) by
    the same mechanism, so it is not a trade worth making. Closing it properly
    needs a different algorithm, not a different constant."""
    assert min_interval_minutes("0,59 0,23 * * 0,1") == 59


def test_an_expression_that_can_never_fire_reports_zero():
    """Feb 30 passes croniter.is_valid but raises inside get_next, so the
    helper returns 0.0. Zero means "no interval could be measured", NOT "zero
    minutes apart" — the guard has to say so explicitly rather than lean on
    0.0 being falsy."""
    assert min_interval_minutes("0 0 30 2 *") == 0.0


from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.sql.selectable import Select  # noqa: E402

MAX = 10


def _client_with(rows, monkeypatch, owned=None, executed=None):
    """A TestClient whose DB returns `rows` for the owner-count query.

    Reuses the _FakeSession shape from test_routes_schedules.py rather than
    inventing a second one. `owned` is what _scoped_schedule finds (the PATCH
    path); `executed`, when a list is passed, collects every statement the
    route issued so a test can assert on the query itself.
    """
    from main import app
    from models import Schedule

    created: list = []

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                created.append(obj)
        async def commit(self): return None
        async def execute(self, stmt):
            if executed is not None:
                executed.append(stmt)

            class _R:
                def scalars(self):
                    class _S:
                        def all(self_): return list(rows)
                    return _S()
                def scalar_one_or_none(self): return owned
            return _R()

    monkeypatch.setattr("routes_schedules.session", lambda: _FakeSession())
    return TestClient(app, raise_server_exceptions=False), created


def _body(**kw):
    b = {"name": "n", "cron_expr": "0 9 * * *", "prompt": "do a thing"}
    b.update(kw)
    return b


def _rows(n):
    import uuid
    from models import Schedule
    return [Schedule(id=uuid.uuid4(), user_email="u@x.com", name=str(i),
                     cron_expr="0 9 * * *", prompt="p") for i in range(n)]


def test_a_regular_user_is_capped(monkeypatch):
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 429, r.text
    assert "10" in r.json()["detail"]
    assert created == [], "rejected the request but still wrote the row"


def test_under_the_cap_still_works(monkeypatch):
    c, created = _client_with(_rows(MAX - 1), monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 201, r.text
    assert len(created) == 1


def test_too_frequent_is_rejected(monkeypatch):
    c, created = _client_with([], monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"},
               json=_body(cron_expr="*/5 * * * *"))
    assert r.status_code == 400, r.text
    assert "15 minutes" in r.json()["detail"]
    assert created == []


def test_an_unmeasurable_expression_is_let_through_on_purpose(monkeypatch):
    """`0 0 30 2 *` can never fire, so it costs the box nothing and is allowed.
    It reaches the guard with gap == 0.0 — the point is that the guard says
    "unmeasurable, allow" out loud instead of falling through a falsy zero."""
    c, created = _client_with([], monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"},
               json=_body(cron_expr="0 0 30 2 *"))
    assert r.status_code == 201, r.text
    assert len(created) == 1


def test_exactly_fifteen_minutes_is_allowed(monkeypatch):
    c, created = _client_with([], monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"},
               json=_body(cron_expr="*/15 * * * *"))
    assert r.status_code == 201, r.text


def test_an_admin_is_exempt_from_both(monkeypatch):
    """Admins keep the old behaviour — the cap protects the box from casual
    use, it is not a security boundary."""
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules",
               headers={"X-User-Email": "a@x.com", "X-User-Admin": "true"},
               json=_body(cron_expr="* * * * *"))
    assert r.status_code == 201, r.text


def test_the_operator_path_is_exempt(monkeypatch):
    """scripts/manage_schedules.py must keep working unchanged."""
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules",
               headers={"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]},
               json=_body(user_email="u@x.com", cron_expr="* * * * *"))
    assert r.status_code == 201, r.text


def test_the_admin_exemption_comes_from_the_x_user_admin_header(monkeypatch):
    """The exemption is driven by that header and nothing else: the identical
    request is refused without it and accepted with it.

    This replaces a test named "a forged admin header cannot reach the
    service", which asserted `"x_user_admin" in inspect.getsource(...)` — true
    from the signature alone, so it passed with the entire guard deleted
    (verified by mutation). Whether a forged header can reach the service is a
    GATEWAY property and is now proved where it lives, in
    api-gateway/tests/test_trust_headers.py.
    """
    c, created = _client_with(_rows(MAX), monkeypatch)
    body = _body(cron_expr="* * * * *")
    assert c.post("/schedules", headers={"X-User-Email": "a@x.com"},
                  json=body).status_code == 400
    assert created == []
    assert c.post("/schedules",
                  headers={"X-User-Email": "a@x.com", "X-User-Admin": "true"},
                  json=body).status_code == 201
    assert len(created) == 1


def test_the_count_is_scoped_to_the_caller(monkeypatch):
    """The one thing that makes this a PER-USER cap rather than a global one.

    _FakeSession.execute used to throw the statement away, so `Schedule.
    user_email == owner` could have been dropped entirely and every test here
    would still have passed. Read the query back instead.
    """
    ex: list = []
    c, created = _client_with(_rows(1), monkeypatch, executed=ex)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 201, r.text
    queries = [str(s.compile(compile_kwargs={"literal_binds": True}))
               for s in ex if isinstance(s, Select)]
    assert queries, "the cap never ran a query"
    assert any("user_email" in q and "'u@x.com'" in q for q in queries), queries


def test_the_operator_path_counts_against_the_body_owner(monkeypatch):
    """Operators are exempt from the cap, so they must not even ask — but if
    that ever changes, the owner is the body's user_email, not the caller."""
    ex: list = []
    c, _ = _client_with(_rows(1), monkeypatch, executed=ex)
    r = c.post("/schedules",
               headers={"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]},
               json=_body(user_email="someone@x.com"))
    assert r.status_code == 201, r.text
    assert [s for s in ex if isinstance(s, Select)] == [], \
        "operators are exempt; the count query should not run at all"


def test_a_spent_one_off_does_not_hold_a_slot_forever(monkeypatch):
    """scheduler.fire_values sets enabled=False on a fired run_once row, and
    only the explicit DELETE endpoint ever removes rows. Ten fired one-offs
    would pin a user at the ceiling permanently, told they "already have 10
    scheduled tasks" about schedules that can never run again."""
    spent = _rows(MAX)
    for r_ in spent:
        r_.run_once, r_.enabled = True, False
    c, created = _client_with(spent, monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 201, r.text
    assert len(created) == 1


def test_a_live_one_off_still_counts(monkeypatch):
    """Only SPENT ones are free — a one-off that has not fired yet is still a
    queued agent run and holds its slot."""
    pending = _rows(MAX)
    for r_ in pending:
        r_.run_once, r_.enabled = True, True
    c, created = _client_with(pending, monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 429, r.text
    assert created == []


# --- PATCH /schedules/{id}: the same floor, or the cap is decorative -------
#
# A non-admin creates `0 9 * * *` (accepted), then edits it to `* * * * *`.
# Both bots ship an Edit modal that PATCHes a user-supplied cron
# (webhook-handler/handlers/commands.py::run_schedule_edit and the
# SCHED_EDITMODAL_PREFIX branch of slack_interactions.py), so this needs no
# tooling — it is two clicks in Discord or Slack.


def _owned(cron_expr="0 9 * * *", email="u@x.com"):
    """A schedule that _scoped_schedule will hand back to the caller."""
    import uuid
    from models import Schedule
    return Schedule(id=uuid.uuid4(), user_email=email, name="n",
                    cron_expr=cron_expr, prompt="p")


def _writes(executed):
    """Only the UPDATE statements — the route also SELECTs to check ownership."""
    from sqlalchemy.sql.dml import Update
    return [s for s in executed if isinstance(s, Update)]


def test_patching_to_every_minute_is_rejected(monkeypatch):
    sched, ex = _owned(), []
    c, _ = _client_with([sched], monkeypatch, owned=sched, executed=ex)
    r = c.patch(f"/schedules/{sched.id}", headers={"X-User-Email": "u@x.com"},
                json={"cron_expr": "* * * * *"})
    assert r.status_code == 400, r.text
    assert "15 minutes" in r.json()["detail"]
    assert _writes(ex) == [], "rejected the edit but still wrote the row"


def test_patching_to_fifteen_minutes_is_allowed(monkeypatch):
    sched, ex = _owned(), []
    c, _ = _client_with([sched], monkeypatch, owned=sched, executed=ex)
    r = c.patch(f"/schedules/{sched.id}", headers={"X-User-Email": "u@x.com"},
                json={"cron_expr": "*/15 * * * *"})
    assert r.status_code == 200, r.text
    assert len(_writes(ex)) == 1


def test_patching_without_a_cron_expr_still_works(monkeypatch):
    """Renaming a schedule must not be dragged through the interval guard."""
    sched, ex = _owned(), []
    c, _ = _client_with([sched], monkeypatch, owned=sched, executed=ex)
    r = c.patch(f"/schedules/{sched.id}", headers={"X-User-Email": "u@x.com"},
                json={"name": "a nicer name"})
    assert r.status_code == 200, r.text
    assert len(_writes(ex)) == 1


def test_an_admin_can_patch_to_every_minute(monkeypatch):
    """Same exemption as create — the cap is not a security boundary."""
    sched, ex = _owned(email="a@x.com"), []
    c, _ = _client_with([sched], monkeypatch, owned=sched, executed=ex)
    r = c.patch(f"/schedules/{sched.id}",
                headers={"X-User-Email": "a@x.com", "X-User-Admin": "true"},
                json={"cron_expr": "* * * * *"})
    assert r.status_code == 200, r.text
    assert len(_writes(ex)) == 1


def test_the_operator_path_can_patch_to_every_minute(monkeypatch):
    """scripts/manage_schedules.py must keep working unchanged."""
    sched, ex = _owned(), []
    c, _ = _client_with([sched], monkeypatch, owned=sched, executed=ex)
    r = c.patch(f"/schedules/{sched.id}",
                headers={"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]},
                json={"cron_expr": "* * * * *"})
    assert r.status_code == 200, r.text
    assert len(_writes(ex)) == 1


# --- Re-enabling: the hole that excluding spent one-offs opens -------------
#
# Once a fired run_once row stops counting, POST /{id}/enable can put it back
# for free. Fire 10, create 10 more, resurrect the first 10, repeat.


def test_resurrecting_a_spent_one_off_is_capped(monkeypatch):
    live = _rows(MAX)
    for r_ in live:
        r_.run_once, r_.enabled = True, True
    spent = _owned()
    spent.run_once, spent.enabled = True, False
    ex: list = []
    c, _ = _client_with(live, monkeypatch, owned=spent, executed=ex)
    r = c.post(f"/schedules/{spent.id}/enable",
               headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 429, r.text
    assert _writes(ex) == [], "refused the enable but still wrote the row"


def test_resuming_a_paused_ordinary_schedule_is_never_capped(monkeypatch):
    """A paused non-one-off never stopped counting, so resuming it adds
    nothing. A user sitting exactly at the ceiling must still be able to."""
    rows = _rows(MAX)
    paused = rows[0]
    paused.enabled = False          # run_once stays falsy
    ex: list = []
    c, _ = _client_with(rows, monkeypatch, owned=paused, executed=ex)
    r = c.post(f"/schedules/{paused.id}/enable",
               headers={"X-User-Email": "u@x.com"})
    assert r.status_code == 200, r.text
    assert len(_writes(ex)) == 1


def test_an_admin_can_resurrect_a_spent_one_off(monkeypatch):
    live = _rows(MAX)
    for r_ in live:
        r_.run_once, r_.enabled = True, True
    spent = _owned(email="a@x.com")
    spent.run_once, spent.enabled = True, False
    c, _ = _client_with(live, monkeypatch, owned=spent)
    r = c.post(f"/schedules/{spent.id}/enable",
               headers={"X-User-Email": "a@x.com", "X-User-Admin": "true"})
    assert r.status_code == 200, r.text


def test_the_operator_path_can_resurrect_a_spent_one_off(monkeypatch):
    live = _rows(MAX)
    for r_ in live:
        r_.run_once, r_.enabled = True, True
    spent = _owned()
    spent.run_once, spent.enabled = True, False
    c, _ = _client_with(live, monkeypatch, owned=spent)
    r = c.post(f"/schedules/{spent.id}/enable",
               headers={"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]})
    assert r.status_code == 200, r.text


# --- The web form must not build a request the API is going to refuse ------
#
# cron.html is browser code and there is no JS harness in this repo (the same
# constraint test_nav_entries.py works around), so this pins the numbers out of
# the source. Weaker than driving the page, but it catches the silent edit that
# puts the form back out of step with MIN_INTERVAL_MINUTES.


def _cron_page() -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1]
            / "static" / "cron.html").read_text(encoding="utf-8")


def test_the_every_n_minutes_control_cannot_go_below_the_floor():
    import re
    from routes_schedules import MIN_INTERVAL_MINUTES
    html = _cron_page()

    m = re.search(r'id="every-n"[^>]*\smin="(\d+)"', html)
    assert m, "the Every N minutes input lost its min attribute"
    assert int(m.group(1)) == MIN_INTERVAL_MINUTES, m.group(0)

    # The input attribute is only advisory — a value typed past it still
    # reaches buildCronFromFriendly, which has to reject it as well.
    m = re.search(r"n < (\d+) \|\| n > 59", html)
    assert m, "buildCronFromFriendly lost its Every-N bounds check"
    assert int(m.group(1)) == MIN_INTERVAL_MINUTES, m.group(0)
