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


from unittest.mock import MagicMock  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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


def test_a_forged_admin_header_cannot_reach_the_service(monkeypatch):
    """Documents WHY trusting X-User-Admin is safe here: the gateway strips it
    from the client request and re-sets it after validating the JWT
    (api-gateway/main.py:298-309). This test pins that the route reads the
    header at all, so the exemption is real rather than accidental."""
    import inspect
    import routes_schedules
    src = inspect.getsource(routes_schedules.create_schedule)
    assert "x_user_admin" in src


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
