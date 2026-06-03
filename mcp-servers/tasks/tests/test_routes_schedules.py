"""routes_schedules — CRUD for tasks.schedules.

Smoke-level tests that verify the X-Cron-Secret gate and basic CRUD shape.
Live DB-backed CRUD (insert + roundtrip persistence) is covered by the
operator-driven e2e in the plan; we mock db.session here so the routes
themselves are exercised without a Postgres process.

This file follows the env-stub pattern from test_healthz.py /
test_publish_access_gate.py: set DATABASE_URL/AIUI_FERNET_KEY/
CRON_SHARED_SECRET BEFORE importing main, so module-level side effects
(routes_schedules.CRON_SECRET) read the right value.
"""
import os
import sys

# Stub env BEFORE importing the app — main.py / routes import db, which
# reads DATABASE_URL at module load.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

CRON_SECRET = "test-secret"
os.environ["CRON_SHARED_SECRET"] = CRON_SECRET

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402


def test_list_requires_secret():
    """Without X-Cron-Secret OR X-User-Email, GET /schedules returns 403."""
    from main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/schedules")
    assert r.status_code == 403


def test_create_with_user_email_scopes_owner(monkeypatch):
    """End-user path: X-User-Email forces user_email even if body says otherwise.

    This is how Open WebUI users will create schedules — the gateway
    injects X-User-Email from the validated JWT.
    """
    from main import app
    from models import Schedule

    rows: list[Schedule] = []

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                rows.append(obj)
        async def commit(self): return None
        async def execute(self, _stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self_): return list(rows)
                    return _S()
            return _R()

    monkeypatch.setattr("routes_schedules.session", lambda: _FakeSession())

    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/schedules",
        headers={"X-User-Email": "alice@example.com"},
        json={
            "user_email": "attacker@evil.com",  # MUST be ignored
            "name": "alice-stocks",
            "cron_expr": "0 20 * * *",
            "persona": "stockbroker",
            "prompt": "watch AAPL",
        },
    )
    assert r.status_code == 201, r.text
    # Schedule should be owned by the JWT-authenticated user, NOT the body claim
    assert len(rows) == 1
    assert rows[0].user_email == "alice@example.com"


def test_user_cannot_see_other_users_schedules(monkeypatch):
    """End-user GET /schedules only returns rows owned by X-User-Email."""
    from main import app
    from models import Schedule
    import uuid

    pre_rows = [
        Schedule(id=uuid.uuid4(), user_email="alice@example.com", name="a",
                 cron_expr="0 8 * * *", prompt="x"),
        Schedule(id=uuid.uuid4(), user_email="bob@example.com", name="b",
                 cron_expr="0 9 * * *", prompt="y"),
    ]

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj): pass
        async def commit(self): return None
        async def execute(self, stmt):
            # Inspect the WHERE clause to honor user_email filtering.
            try:
                compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            except Exception:
                compiled = ""
            class _R:
                def __init__(self, rs): self._rs = rs
                def scalars(self):
                    class _S:
                        def all(self_inner): return self._rs
                    return _S()
            if "alice@example.com" in compiled:
                return _R([pre_rows[0]])
            if "bob@example.com" in compiled:
                return _R([pre_rows[1]])
            return _R(pre_rows)

    monkeypatch.setattr("routes_schedules.session", lambda: _FakeSession())

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/schedules", headers={"X-User-Email": "alice@example.com"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["user_email"] == "alice@example.com"


def test_create_then_list(monkeypatch):
    """POST /schedules with a valid X-Cron-Secret returns 201 + an id.
    GET /schedules with the same secret returns a list including the row.

    db.session is mocked: the route still constructs the Schedule ORM
    instance correctly, but the AsyncSession.add/commit/execute are
    no-ops. GET is faked to return the previously-created in-memory rows.
    """
    from main import app
    from models import Schedule
    import uuid

    # In-memory row store the mocked session pretends to own.
    rows: list[Schedule] = []

    class _FakeResultScalars:
        def __init__(self, items): self._items = items
        def all(self): return list(self._items)

    class _FakeResult:
        def __init__(self, items): self._items = items
        def scalars(self): return _FakeResultScalars(self._items)

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                rows.append(obj)
        async def commit(self): return None
        async def execute(self, _stmt):
            return _FakeResult(rows)

    def _fake_session_factory():
        return _FakeSession()

    monkeypatch.setattr("routes_schedules.session", _fake_session_factory)

    # NB: NOT a context-manager — that triggers FastAPI lifespan startup,
    # which tries to connect to the stub DB and crashes. Bare TestClient
    # still routes requests; lifespan is just skipped.
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/schedules",
        headers={"X-Cron-Secret": CRON_SECRET},
        json={
            "user_email": "x@y.com",
            "name": "test-sched",
            "cron_expr": "*/5 * * * *",
            "persona": "test",
            "prompt": "say hi",
        },
    )
    assert r.status_code == 201, r.text
    sched_id = r.json()["id"]
    # UUID round-trip sanity
    uuid.UUID(sched_id)

    r = c.get("/schedules", headers={"X-Cron-Secret": CRON_SECRET})
    assert r.status_code == 200, r.text
    assert any(s["id"] == sched_id for s in r.json())


def _make_capture_session(rows):
    """A mocked db.session whose add() captures Schedule rows into `rows`."""
    from models import Schedule

    class _FakeResult:
        def scalars(self):
            class _S:
                def all(self_inner): return list(rows)
            return _S()

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                rows.append(obj)
        async def commit(self): return None
        async def execute(self, _stmt):
            return _FakeResult()

    return lambda: _FakeSession()


def test_create_with_delivery_platform_slack(monkeypatch):
    """POST /schedules with delivery_platform='slack' persists 'slack' on the row."""
    from main import app

    rows = []
    monkeypatch.setattr("routes_schedules.session", _make_capture_session(rows))

    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/schedules",
        headers={"X-Cron-Secret": CRON_SECRET},
        json={
            "user_email": "x@y.com",
            "name": "slack-sched",
            "cron_expr": "*/5 * * * *",
            "persona": "test",
            "prompt": "say hi",
            "delivery_platform": "slack",
        },
    )
    assert r.status_code == 201, r.text
    assert len(rows) == 1
    assert rows[0].delivery_platform == "slack"


def test_create_defaults_delivery_platform_discord(monkeypatch):
    """Omitting delivery_platform defaults the inserted row to 'discord'."""
    from main import app

    rows = []
    monkeypatch.setattr("routes_schedules.session", _make_capture_session(rows))

    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(
        "/schedules",
        headers={"X-Cron-Secret": CRON_SECRET},
        json={
            "user_email": "x@y.com",
            "name": "discord-sched",
            "cron_expr": "*/5 * * * *",
            "persona": "test",
            "prompt": "say hi",
        },
    )
    assert r.status_code == 201, r.text
    assert len(rows) == 1
    assert rows[0].delivery_platform == "discord"
