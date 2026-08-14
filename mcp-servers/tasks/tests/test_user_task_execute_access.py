"""POST /api/tasks/{task_id}/execute is what actually starts a build, so a
regular user has to reach it — projects.html calls it the instant a project is
created, and preview.html's overlay re-fires it when the first call never
landed. While it demanded the admin header the feature was half-done: a
non-admin got a project card and a task that stayed `pending` forever.

Same shape as the relaxations in 2a931c158..23c4e0a22. The body already does
the real authorization — `_require_role(..., "editor")` when the task carries a
slug, assignee otherwise — so the dependency only ever stopped a user from
building their OWN app.

Two things do NOT survive the relaxation:

  * the team bucket (`team@aiui.local`). Executing is a WRITE that spends the
    agent budget and rewrites files; letting any signed-in user fire one at the
    AIUI team's queue for the price of guessing a UUID is worse than the read
    leak aa669cd92 closed. Admins keep it; so does a capability, which is
    already minted for this exact task_id.
  * admin-ness. A capability principal is still non-admin, so
    `_require_role` re-checks its live role instead of waving it through.
"""
import importlib
import inspect
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

import routes_execution
from auth import current_admin_or_capability, current_user_or_capability
from main import app
from models import ProjectMember, TaskItem

TEAM = "team@aiui.local"
USER_EMAIL = "mia@example.com"
OTHER_EMAIL = "someone-else@example.com"
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
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _ScriptedSession:
    """Returns a pre-scripted row per execute() call, in order.

    Wider than the read-access version because /execute writes: it takes the
    advisory lock (execute with bind params), reaps orphan executions, adds an
    execution row and commits.
    """

    def __init__(self, script):
        self._script = list(script)
        self.committed = False

    async def execute(self, q, params=None):
        row = self._script.pop(0) if self._script else None
        return _Result([row] if row is not None else [])

    def add(self, obj):
        pass

    async def refresh(self, obj):
        pass

    async def commit(self):
        self.committed = True


def _task(assignee_email, slug=None, task_id=None, status="pending"):
    return TaskItem(
        id=task_id or uuid.uuid4(),
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name=assignee_email.split("@")[0],
        assignee_email=assignee_email,
        description="build me a thing",
        priority="IMPORTANT",
        status=status,
        max_attempts=1,
        attempt_count=0,
        conversation_history=[],
        built_app_slug=slug,
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def scripted(monkeypatch):
    """Install a scripted DB session and stub the background agent run."""
    async def _noop_run_execution(*a, **kw):
        return None

    monkeypatch.setattr(routes_execution, "_run_execution", _noop_run_execution)

    def _install(*rows):
        @asynccontextmanager
        async def _fake_session():
            yield _ScriptedSession(rows)
        monkeypatch.setattr(routes_execution, "session", _fake_session)
    return _install


async def _post(task_id, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(f"/api/tasks/{task_id}/execute", headers=headers)


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_execute_does_not_demand_the_admin_header():
    assert current_admin_or_capability not in _deps(routes_execution.execute), (
        "POST /api/tasks/{id}/execute still falls back to the admin header, so a "
        "regular user's project is created but the build never starts")


def test_execute_still_requires_a_signed_in_user():
    assert current_user_or_capability in _deps(routes_execution.execute), (
        "POST /api/tasks/{id}/execute lost its authentication")


async def test_anonymous_cannot_execute(scripted):
    scripted(_task(USER_EMAIL))
    r = await _post(uuid.uuid4(), {})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# What a regular user may start
# ---------------------------------------------------------------------------

async def test_regular_user_can_execute_their_own_task(scripted):
    """The whole point: a non-admin creates a project and the build starts."""
    tid = uuid.uuid4()
    # select item; _require_role: no member row, then the implicit-owner
    # TaskItem lookup; then lock / reap / supabase-config all read nothing.
    scripted(_task(USER_EMAIL, slug="my-app", task_id=tid), None,
             _task(USER_EMAIL, slug="my-app", task_id=tid))
    r = await _post(tid, USER_HEADERS)
    assert r.status_code in (200, 202), (
        f"a regular user cannot start their own build: {r.status_code} {r.text}")
    assert r.json()["status"] == "running"


async def test_regular_user_can_execute_their_own_slugless_task(scripted):
    tid = uuid.uuid4()
    scripted(_task(USER_EMAIL, task_id=tid))
    r = await _post(tid, USER_HEADERS)
    assert r.status_code in (200, 202), r.text


async def test_regular_user_cannot_execute_a_strangers_task(scripted):
    tid = uuid.uuid4()
    scripted(_task(OTHER_EMAIL, task_id=tid))
    r = await _post(tid, USER_HEADERS)
    assert r.status_code == 403


async def test_regular_user_cannot_execute_a_strangers_project(scripted):
    """Slug present → _require_role: no member row, no TaskItem of theirs."""
    tid = uuid.uuid4()
    scripted(_task(OTHER_EMAIL, slug="their-app", task_id=tid), None, None)
    r = await _post(tid, USER_HEADERS)
    assert r.status_code == 403


async def test_regular_user_cannot_execute_a_team_bucket_task(scripted):
    """A build is a write. Guessing a UUID must not let a regular user spend
    the agent on the AIUI team's queue."""
    tid = uuid.uuid4()
    scripted(_task(TEAM, task_id=tid))
    r = await _post(tid, USER_HEADERS)
    assert r.status_code == 403, (
        "a regular user started a build on a shared team-bucket task")


async def test_missing_task_is_still_404(scripted):
    scripted()
    r = await _post(uuid.uuid4(), USER_HEADERS)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Project roles
# ---------------------------------------------------------------------------

async def test_project_editor_can_execute(scripted):
    tid = uuid.uuid4()
    scripted(
        _task(OTHER_EMAIL, slug="shared-app", task_id=tid),
        ProjectMember(slug="shared-app", user_email=USER_EMAIL, role="editor",
                      added_by=ADMIN_EMAIL),
    )
    r = await _post(tid, USER_HEADERS)
    assert r.status_code in (200, 202), r.text


async def test_project_viewer_cannot_execute(scripted):
    tid = uuid.uuid4()
    scripted(
        _task(OTHER_EMAIL, slug="shared-app", task_id=tid),
        ProjectMember(slug="shared-app", user_email=USER_EMAIL, role="viewer",
                      added_by=ADMIN_EMAIL),
    )
    r = await _post(tid, USER_HEADERS)
    assert r.status_code == 403, "a viewer started a build on someone else's app"


# ---------------------------------------------------------------------------
# Admins keep today's behaviour exactly
# ---------------------------------------------------------------------------

async def test_admin_can_still_execute_a_team_bucket_task(scripted):
    tid = uuid.uuid4()
    scripted(_task(TEAM, task_id=tid))
    r = await _post(tid, ADMIN_HEADERS)
    assert r.status_code in (200, 202), (
        f"the admin task panel lost the team bucket: {r.status_code} {r.text}")


async def test_admin_can_still_execute_a_strangers_project(scripted):
    """is_admin=True short-circuits _require_role, so no membership row is
    scripted — an admin must still not need one."""
    tid = uuid.uuid4()
    scripted(_task(OTHER_EMAIL, slug="their-app", task_id=tid))
    r = await _post(tid, ADMIN_HEADERS)
    assert r.status_code in (200, 202), r.text


# ---------------------------------------------------------------------------
# The capability path (Visual Editor deep link from Discord/Slack)
# ---------------------------------------------------------------------------

def _cap(monkeypatch, owner, slug, task_id):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "s3cr3t-for-tests")
    import edit_capability
    importlib.reload(edit_capability)
    return edit_capability.mint_capability(owner, slug, str(task_id))


async def test_capability_can_still_execute(scripted, monkeypatch):
    tid = uuid.uuid4()
    cap = _cap(monkeypatch, "owner@x.com", "their-app", tid)
    scripted(
        _task(OTHER_EMAIL, slug="their-app", task_id=tid),
        ProjectMember(slug="their-app", user_email="owner@x.com", role="owner",
                      added_by=ADMIN_EMAIL),
    )
    r = await _post(tid, {"X-Edit-Capability": cap})
    assert r.status_code in (200, 202), (
        f"the visual-editor deep link lost its build/retry button: {r.text}")


async def test_capability_is_not_treated_as_admin(scripted, monkeypatch):
    """A capability proves ONE task, never admin: with no live role on the
    project, _require_role must still reject it."""
    tid = uuid.uuid4()
    cap = _cap(monkeypatch, "owner@x.com", "their-app", tid)
    scripted(_task(OTHER_EMAIL, slug="their-app", task_id=tid), None, None)
    r = await _post(tid, {"X-Edit-Capability": cap})
    assert r.status_code == 403, "a capability was waved through as admin"


async def test_capability_for_a_different_task_is_rejected(scripted, monkeypatch):
    cap = _cap(monkeypatch, "owner@x.com", "their-app", uuid.uuid4())
    scripted(_task(TEAM, task_id=uuid.uuid4()))
    r = await _post(uuid.uuid4(), {"X-Edit-Capability": cap})
    assert r.status_code == 403
