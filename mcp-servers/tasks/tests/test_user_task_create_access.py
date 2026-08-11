"""POST /api/tasks is how the App Builder creates a project, so a regular user
has to reach it — but it is also the widest-open write in the service, and the
admin header was the only thing holding two doors shut.

1. `assignee`. "self" is the caller, "team" is the shared bucket, and anything
   else is resolved through AssigneeMap to ANOTHER person's inbox. A regular
   user must not be able to file work at a colleague or at the team bucket.

2. `slug`. CreateTaskRequest declares it as a bare `str | None` with no format
   check, and it is used two ways:
     - as a filesystem path — `_ensure_app_skeleton` / `_copy_template_app`
       join it onto `apps/`, so "../../x" escapes the workspace entirely;
     - as a project identity — routes_projects._require_role treats "there is a
       TaskItem with this built_app_slug assigned to me" as implicit OWNERSHIP.
   So creating a task with someone else's slug would BOTH overwrite their app's
   files and make the caller an owner of their project (publish, rollback,
   delete, invite, link a database). That was survivable while the route was
   admin-only; it is not survivable once any signed-in user can post to it.

Admins keep today's behaviour byte for byte — both guards are conditional on
`not user.is_admin`.
"""
import inspect
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import routes_aiuibuilder
import routes_projects
import routes_tasks
from auth import current_admin, current_user
from main import app

TEAM = "team@aiui.local"
USER_EMAIL = "mia@example.com"
ADMIN_EMAIL = "ralph@aiui.com"
OTHER_EMAIL = "lukas@aiui.com"
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
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0]


class _FakeSession:
    """Enough of AsyncSession for create_task, with no Postgres.

    `touched` records whether the route reached the database at all, which is
    how the rejection tests prove the 403 lands BEFORE any write.
    """

    def __init__(self):
        self.added = []
        self.touched = False
        self.committed = False

    async def execute(self, q):
        self.touched = True
        return _Result()

    def add(self, obj):
        self.touched = True
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        # Stand in for the server-side column defaults a real INSERT fills in.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()
        if getattr(obj, "attempt_count", None) is None:
            obj.attempt_count = 0
        if getattr(obj, "conversation_history", None) is None:
            obj.conversation_history = []


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Fake DB session + a throwaway workspace, so nothing touches real state."""
    fake = _FakeSession()

    @asynccontextmanager
    async def _fake_session():
        yield fake

    monkeypatch.setattr(routes_tasks, "session", _fake_session)
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("TASKS_ASSIGNEE_MAP", f"lukas:{OTHER_EMAIL}")
    return fake


async def _post(body, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/api/tasks", json=body, headers=headers)


def _body(**over):
    base = {
        "description": "A task description that is long enough to be real.",
        "action_type": "RESEARCH",
        "priority": "IMPORTANT",
        "assignee": "self",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_create_task_does_not_demand_the_admin_header():
    assert current_admin not in _deps(routes_tasks.create_task), (
        "POST /api/tasks still requires the admin header, so a regular user "
        "cannot start a project")


def test_create_task_still_requires_a_signed_in_user():
    assert current_user in _deps(routes_tasks.create_task), (
        "POST /api/tasks lost its authentication")


async def test_anonymous_cannot_create_a_task(db):
    r = await _post(_body(), {})
    assert r.status_code == 401
    assert not db.touched


# ---------------------------------------------------------------------------
# Boundary 1 — a regular user may only file work against themselves
# ---------------------------------------------------------------------------

async def test_regular_user_cannot_assign_a_task_to_another_person(db):
    r = await _post(_body(assignee="lukas"), USER_HEADERS)
    assert r.status_code == 403, "a regular user can dump work in someone else's queue"
    assert not db.touched, "the rejected task still reached the database"


async def test_regular_user_cannot_file_into_the_shared_team_bucket(db):
    r = await _post(_body(assignee="team"), USER_HEADERS)
    assert r.status_code == 403, "a regular user can post into the team bucket"
    assert not db.touched


async def test_unknown_assignee_names_do_not_slip_through(db):
    """AssigneeMap.resolve falls back to the TEAM bucket for a name it does not
    know, so an unmapped name must be rejected too rather than silently
    becoming a team task."""
    r = await _post(_body(assignee="nobody-in-the-map"), USER_HEADERS)
    assert r.status_code == 403


async def test_regular_user_can_create_a_task_for_themselves(db):
    r = await _post(_body(assignee="self"), USER_HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["assignee_email"] == USER_EMAIL


async def test_assignee_defaults_to_the_caller(db):
    body = _body()
    body.pop("assignee")
    r = await _post(body, USER_HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["assignee_email"] == USER_EMAIL


# ---------------------------------------------------------------------------
# Boundary 1 — admins keep today's behaviour exactly
# ---------------------------------------------------------------------------

async def test_admin_can_still_assign_to_the_team_bucket(db):
    r = await _post(_body(assignee="team"), ADMIN_HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["assignee_email"] == TEAM


async def test_admin_can_still_assign_to_another_person(db):
    r = await _post(_body(assignee="lukas"), ADMIN_HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["assignee_email"] == OTHER_EMAIL


# ---------------------------------------------------------------------------
# Boundary 2 — the caller-supplied slug is a path AND a project identity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "..", "a/b", "a\\b", "Upper", "x", "has space",
            "-leading", "app;rm -rf /"]
)
async def test_regular_user_cannot_supply_an_unsafe_slug(db, tmp_path, bad):
    r = await _post(
        _body(action_type="BUILD", template_key="landing", storage="none", slug=bad),
        USER_HEADERS,
    )
    assert r.status_code == 422, f"{bad!r} was accepted as a project slug"
    escaped = [p for p in tmp_path.parent.iterdir() if p.name == "etc"]
    assert not escaped, "a slug escaped the workspace and wrote to disk"
    assert not (tmp_path / "apps").exists(), "a rejected slug still scaffolded a directory"


async def test_regular_user_cannot_claim_a_slug_that_belongs_to_someone_else(
    db, monkeypatch
):
    """Reusing another user's slug would overwrite their app's files AND make
    the caller an implicit owner of their project via _require_role."""
    async def _taken(s, slug):
        return True

    async def _no_role(s, slug, email, min_role, **kw):
        raise HTTPException(status_code=403, detail="Not a member of this project")

    monkeypatch.setattr(routes_aiuibuilder, "_slug_taken", _taken)
    monkeypatch.setattr(routes_projects, "_require_role", _no_role)

    r = await _post(
        _body(action_type="BUILD", template_key="landing", storage="none",
              slug="someones-app"),
        USER_HEADERS,
    )
    assert r.status_code == 409, "a regular user hijacked another user's project slug"
    assert not db.committed, "the rejected task was still written"


async def test_hijacked_slug_never_reaches_disk(db, monkeypatch, tmp_path):
    async def _taken(s, slug):
        return True

    async def _no_role(s, slug, email, min_role, **kw):
        raise HTTPException(status_code=403, detail="Not a member of this project")

    monkeypatch.setattr(routes_aiuibuilder, "_slug_taken", _taken)
    monkeypatch.setattr(routes_projects, "_require_role", _no_role)

    await _post(
        _body(action_type="BUILD", template_key="landing", storage="none",
              slug="someones-app"),
        USER_HEADERS,
    )
    assert not (tmp_path / "apps" / "someones-app").exists(), (
        "the rejected build still overwrote the victim's app directory")


async def test_regular_user_can_reuse_a_slug_they_already_own(db, monkeypatch):
    async def _taken(s, slug):
        return True

    async def _is_owner(s, slug, email, min_role, **kw):
        return "owner"

    monkeypatch.setattr(routes_aiuibuilder, "_slug_taken", _taken)
    monkeypatch.setattr(routes_projects, "_require_role", _is_owner)

    r = await _post(
        _body(action_type="BUILD", template_key="landing", storage="none",
              slug="my-own-app"),
        USER_HEADERS,
    )
    assert r.status_code == 201, r.text


async def test_regular_user_can_create_a_project_with_a_fresh_slug(db):
    r = await _post(
        _body(action_type="BUILD", template_key="landing", storage="none",
              slug="mias-new-app"),
        USER_HEADERS,
    )
    assert r.status_code == 201, r.text
    assert r.json()["built_app_slug"] == "mias-new-app"


async def test_admin_slug_handling_is_unchanged(db, monkeypatch):
    """The two slug guards are conditional on `not user.is_admin`, so an admin
    still gets today's unchecked behaviour."""
    async def _taken(s, slug):
        return True

    async def _no_role(s, slug, email, min_role, **kw):
        raise HTTPException(status_code=403, detail="Not a member of this project")

    monkeypatch.setattr(routes_aiuibuilder, "_slug_taken", _taken)
    monkeypatch.setattr(routes_projects, "_require_role", _no_role)

    r = await _post(
        _body(action_type="BUILD", template_key="landing", storage="none",
              slug="Legacy.Slug_With_Dots"),
        ADMIN_HEADERS,
    )
    assert r.status_code == 201, r.text
