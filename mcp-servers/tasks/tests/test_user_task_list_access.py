"""Projects are per-user, so listing them must not demand the admin header.

A regular user opening the App Builder page got "You must be signed in as an
admin to view projects." (static/projects.html) because GET /api/tasks answered
403: the route hung `current_admin` off its signature even though the
`is_project` / `has_built_app` branches were ALREADY scoped to
`assignee_email == me OR built_app_slug IN (projects I am a member of)`.

Same redundant-gate shape as the Supabase routes in 927d7a051: relaxing
"admin AND owner" to "owner" takes nothing away.

The DEFAULT branch (neither flag) is different and is NOT merely redundant —
it is the admin task panel and widens the scope to the shared team bucket
(`team@aiui.local`). Opening the route without touching that branch would hand
every signed-in user the team's tasks, so the team bucket is now conditional on
`user.is_admin`.

These tests read the real FastAPI dependency objects and the real SQL the route
builds, so neither a comment nor a renamed helper can satisfy them.
"""
import inspect
import os
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

import routes_tasks
from auth import current_admin, current_user
from main import app

TEAM = "team@aiui.local"
USER_EMAIL = "mia@example.com"
ADMIN_EMAIL = "ralph@aiui.com"
USER_HEADERS = {"X-User-Email": USER_EMAIL}
ADMIN_HEADERS = {"X-User-Email": ADMIN_EMAIL, "X-User-Admin": "true"}


def _deps(func):
    """The dependency callables declared in a route's signature."""
    out = []
    for param in inspect.signature(func).parameters.values():
        default = param.default
        if default is not inspect.Parameter.empty and hasattr(default, "dependency"):
            out.append(default.dependency)
    return out


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _CapturingSession:
    """Stands in for a real Postgres session: records the query, returns none.

    The filtering under test happens in SQL, so the assertion has to be on the
    statement the route builds, not on rows a fake would hand back.
    """

    def __init__(self, seen):
        self.seen = seen

    async def execute(self, q):
        self.seen.append(q)
        return _Result([])


@pytest.fixture
def seen_queries(monkeypatch):
    seen = []

    @asynccontextmanager
    async def _fake_session():
        yield _CapturingSession(seen)

    monkeypatch.setattr(routes_tasks, "session", _fake_session)
    return seen


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


async def _get(url, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(url, headers=headers)


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_list_tasks_does_not_demand_the_admin_header():
    assert current_admin not in _deps(routes_tasks.list_tasks), (
        "GET /api/tasks still requires the admin header, so a regular user "
        "cannot see their own projects")


def test_list_tasks_still_requires_a_signed_in_user():
    assert current_user in _deps(routes_tasks.list_tasks), (
        "GET /api/tasks lost its authentication")


async def test_anonymous_caller_is_still_rejected(seen_queries):
    r = await _get("/api/tasks?is_project=true", {})
    assert r.status_code == 401
    assert not seen_queries, "an anonymous caller reached the database"


# ---------------------------------------------------------------------------
# The bug the user reported
# ---------------------------------------------------------------------------

async def test_regular_user_can_list_their_projects(seen_queries):
    r = await _get("/api/tasks?is_project=true&limit=200", USER_HEADERS)
    assert r.status_code == 200, (
        "the App Builder page still shows 'You must be signed in as an admin'")


async def test_regular_user_can_list_their_built_apps(seen_queries):
    r = await _get("/api/tasks?has_built_app=true&status=done", USER_HEADERS)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# The privilege boundary: opening the route must not widen what it returns
# ---------------------------------------------------------------------------

async def test_project_list_is_scoped_to_the_caller(seen_queries):
    await _get("/api/tasks?is_project=true", USER_HEADERS)
    sql = _sql(seen_queries[0])
    assert USER_EMAIL in sql
    assert TEAM not in sql, "the project list leaked the shared team bucket"


async def test_built_app_list_is_scoped_to_the_caller(seen_queries):
    await _get("/api/tasks?has_built_app=true&status=done", USER_HEADERS)
    sql = _sql(seen_queries[0])
    assert USER_EMAIL in sql
    assert TEAM not in sql, "the built-app list leaked the shared team bucket"


async def test_default_branch_hides_the_team_bucket_from_a_regular_user(seen_queries):
    """The task-panel view. A regular user gets their own tasks and nothing
    else — the team bucket is other people's work."""
    r = await _get("/api/tasks?status=pending", USER_HEADERS)
    assert r.status_code == 200
    sql = _sql(seen_queries[0])
    assert USER_EMAIL in sql
    assert TEAM not in sql, (
        "a regular user would receive the shared team bucket's tasks")


async def test_default_branch_still_gives_an_admin_the_team_bucket(seen_queries):
    """Admins keep today's behaviour exactly."""
    r = await _get("/api/tasks?status=pending", ADMIN_HEADERS)
    assert r.status_code == 200
    sql = _sql(seen_queries[0])
    assert ADMIN_EMAIL in sql
    assert TEAM in sql, "the admin task panel lost the shared team bucket"


async def test_project_branch_never_includes_the_team_bucket_even_for_an_admin(
    seen_queries,
):
    """Projects stay private to owner + invited members, admin or not."""
    await _get("/api/tasks?is_project=true", ADMIN_HEADERS)
    assert TEAM not in _sql(seen_queries[0])


def test_the_page_no_longer_claims_admin_is_required():
    """The exact sentence the user reported. current_user never raises 403, so
    the only way to reach this branch now is to be signed out entirely —
    telling that person they need to be an admin sends them to the wrong fix."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(here, "static", "projects.html"), encoding="utf-8").read()
    assert "signed in as an admin to view projects" not in html
