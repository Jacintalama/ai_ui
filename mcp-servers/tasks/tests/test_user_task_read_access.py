"""GET /api/tasks/{task_id} is how the App Builder watches a build, so a
regular user has to reach it — preview.html polls it for status.

The body already does the real work: assignee, or the shared team bucket, or a
row in project_members, else 403. Only the `current_admin_or_capability`
dependency stood in front of it, and for the no-capability path that meant a
regular user could not read their OWN task.

One thing does NOT survive the relaxation. The team bucket (`team@aiui.local`)
is the AIUI team's queue; keeping that shortcut for everybody would let any
signed-in user pull team tasks — descriptions, plans, results — by guessing a
UUID. It is now conditional on being an admin, or on holding a capability
minted for this exact task_id (which is what the Discord/Slack "Visual Editor"
deep link carries, and which is already bound to one task).
"""
import importlib
import inspect
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

import routes_tasks
from auth import current_admin_or_capability, current_user_or_capability
from main import app
from models import ProjectMember, TaskItem

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
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _ScriptedSession:
    """Returns a pre-scripted row per execute() call, in order."""

    def __init__(self, script):
        self._script = list(script)

    async def execute(self, q):
        row = self._script.pop(0) if self._script else None
        return _Result([row] if row is not None else [])


def _task(assignee_email, slug=None, task_id=None):
    return TaskItem(
        id=task_id or uuid.uuid4(),
        meeting_id=uuid.uuid4(),
        action_type="BUILD",
        assignee_name=assignee_email.split("@")[0],
        assignee_email=assignee_email,
        description="build me a thing",
        priority="IMPORTANT",
        status="running",
        max_attempts=1,
        attempt_count=0,
        conversation_history=[],
        built_app_slug=slug,
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def scripted(monkeypatch):
    """Install a scripted DB session; returns the installer."""
    def _install(*rows):
        @asynccontextmanager
        async def _fake_session():
            yield _ScriptedSession(rows)
        monkeypatch.setattr(routes_tasks, "session", _fake_session)
    return _install


async def _get(task_id, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(f"/api/tasks/{task_id}", headers=headers)


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_get_task_does_not_demand_the_admin_header():
    assert current_admin_or_capability not in _deps(routes_tasks.get_task), (
        "GET /api/tasks/{id} still falls back to the admin header, so a "
        "regular user cannot watch their own build")


def test_get_task_still_requires_a_signed_in_user():
    assert current_user_or_capability in _deps(routes_tasks.get_task), (
        "GET /api/tasks/{id} lost its authentication")


async def test_anonymous_cannot_read_a_task(scripted):
    scripted(_task(USER_EMAIL))
    r = await _get(uuid.uuid4(), {})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# What a regular user may read
# ---------------------------------------------------------------------------

async def test_regular_user_can_read_their_own_task(scripted):
    tid = uuid.uuid4()
    scripted(_task(USER_EMAIL, task_id=tid))
    r = await _get(tid, USER_HEADERS)
    assert r.status_code == 200, "a user cannot watch their own build"
    assert r.json()["assignee_email"] == USER_EMAIL


async def test_regular_user_can_read_a_task_for_a_project_they_are_in(scripted):
    tid = uuid.uuid4()
    scripted(
        _task("someone-else@example.com", slug="shared-app", task_id=tid),
        ProjectMember(slug="shared-app", user_email=USER_EMAIL, role="editor",
                      added_by=ADMIN_EMAIL),
    )
    r = await _get(tid, USER_HEADERS)
    assert r.status_code == 200


async def test_regular_user_cannot_read_a_strangers_task(scripted):
    tid = uuid.uuid4()
    scripted(_task("someone-else@example.com", slug="their-app", task_id=tid), None)
    r = await _get(tid, USER_HEADERS)
    assert r.status_code == 403


async def test_regular_user_cannot_read_a_team_bucket_task(scripted):
    """The bug this change must not introduce: guessing a UUID must not hand a
    regular user the AIUI team's queue."""
    tid = uuid.uuid4()
    scripted(_task(TEAM, task_id=tid), None)
    r = await _get(tid, USER_HEADERS)
    assert r.status_code == 403, (
        "a regular user read a shared team-bucket task by task id")


async def test_missing_task_is_still_404(scripted):
    scripted()
    r = await _get(uuid.uuid4(), USER_HEADERS)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Admins and the capability path keep today's behaviour
# ---------------------------------------------------------------------------

async def test_admin_can_still_read_a_team_bucket_task(scripted):
    tid = uuid.uuid4()
    scripted(_task(TEAM, task_id=tid))
    r = await _get(tid, ADMIN_HEADERS)
    assert r.status_code == 200, "the admin task panel lost the team bucket"


async def test_admin_can_still_read_a_strangers_task_via_membership(scripted):
    tid = uuid.uuid4()
    scripted(
        _task("someone-else@example.com", slug="their-app", task_id=tid),
        ProjectMember(slug="their-app", user_email=ADMIN_EMAIL, role="viewer",
                      added_by=ADMIN_EMAIL),
    )
    r = await _get(tid, ADMIN_HEADERS)
    assert r.status_code == 200


async def test_capability_still_reads_a_team_bucket_task(scripted, monkeypatch):
    """The Visual Editor deep link (Discord/Slack) carries no admin header —
    it carries a capability bound to this exact task_id."""
    monkeypatch.setenv("OAUTH_STATE_SECRET", "s3cr3t-for-tests")
    import edit_capability
    importlib.reload(edit_capability)

    tid = uuid.uuid4()
    cap = edit_capability.mint_capability("owner@x.com", "their-app", str(tid))
    scripted(_task(TEAM, slug="their-app", task_id=tid))
    r = await _get(tid, {"X-Edit-Capability": cap})
    assert r.status_code == 200, "the visual-editor deep link lost read access"


async def test_capability_for_a_different_task_is_rejected(scripted, monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "s3cr3t-for-tests")
    import edit_capability
    importlib.reload(edit_capability)

    cap = edit_capability.mint_capability("owner@x.com", "their-app", str(uuid.uuid4()))
    scripted(_task(TEAM, task_id=uuid.uuid4()))
    r = await _get(uuid.uuid4(), {"X-Edit-Capability": cap})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# The dependency itself
# ---------------------------------------------------------------------------

class _Req:
    def __init__(self, headers):
        self.headers = headers


def test_dep_accepts_a_plain_user_without_the_admin_header():
    u = current_user_or_capability(uuid.uuid4(), _Req({"x-user-email": "USER@x.com"}))
    assert u.email == "user@x.com"
    assert u.is_admin is False
    assert u.via_capability is False


def test_dep_carries_the_admin_header_through():
    u = current_user_or_capability(
        uuid.uuid4(), _Req({"x-user-email": "a@x.com", "x-user-admin": "true"}))
    assert u.is_admin is True


def test_dep_rejects_a_missing_email():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        current_user_or_capability(uuid.uuid4(), _Req({}))
    assert e.value.status_code == 401


def test_dep_marks_the_capability_path_and_grants_no_admin(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "s3cr3t-for-tests")
    import edit_capability
    importlib.reload(edit_capability)
    tid = uuid.uuid4()
    cap = edit_capability.mint_capability("Owner@X.com", "my-app", str(tid))
    u = current_user_or_capability(tid, _Req({"x-edit-capability": cap}))
    assert u.email == "owner@x.com"
    assert u.is_admin is False, "a capability must never confer admin"
    assert u.via_capability is True
