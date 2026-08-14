"""Exporting, docs and version history are for the people who OWN the app.

"Take Your App With You" shipped 2026-07-27 behind `current_admin_or_capability_
for_slug`, so the owners it was built for cannot use it — only the AIUI team can
download their app.

These are NOT the redundant gates relaxed in 2a931c158..dda2d632f. Those routes
each enforced ownership in the body, so the admin header was a second lock on a
locked door. Here the picture is uneven, and it was checked route by route
rather than assumed:

  * `list_versions` and `get_docs` DO have a body check — `_user_can_see_project`
    — but it is not a role check. It returns True for anything sitting in the
    `team@aiui.local` bucket, for EVERY signed-in user, because it matches
    `user_email IN (email, TEAM_EMAIL)`. Swapping the dependency alone would
    therefore have handed a stranger the team's READMEs and git history.
  * `export_guide` and `export_bundle` have no check of any kind. Swapping the
    dependency alone would have handed any signed-in user the full source, the
    git history and the injected Supabase config of any app on the box.

So the role check is written first and the gate is relaxed second:

  * export + export/guide -> `owner` (it hands over the whole app)
  * versions + docs       -> `viewer`, the precedent `get_supabase` sets for a
                             pure read
  * all four              -> any signed-in user at the dependency layer

Admins are deliberately unchanged, not merely "still allowed". versions/docs
keep `_user_can_see_project` as the first of two checks (the pattern
`_publish_slug` already uses in this module), so an admin faces exactly the gate
they face today and the new role check is what a non-admin must additionally
pass. export/export-guide had no gate for an admin, so their new check takes the
`is_admin=` bypass and an admin is likewise unchanged.

The assertions below read the real FastAPI dependency objects and drive the real
route bodies against the real bind parameters of the real queries, so neither a
comment nor a renamed helper can satisfy them.
"""
import importlib
import inspect
import os
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql.elements import TextClause

import routes_projects
# Imported at module scope on purpose: test_edit_capability_auth.py reloads
# `auth`, which rebinds these names to NEW function objects while the route
# signatures still hold the originals. Importing inside a test would compare
# against the post-reload object and fail on identity alone.
from auth import (current_admin, current_admin_or_capability_for_slug,
                  current_user_or_capability_for_slug)
from main import app
from models import ProjectMember, ProjectSupabase, TaskItem

SLUG = "cool-app"
TEAM = "team@aiui.local"
OWNER = "owner@example.com"
EDITOR = "editor@example.com"
VIEWER = "viewer@example.com"
STRANGER = "stranger@example.com"
ADMIN = "ralph@aiui.com"

ADMIN_HEADERS = {"X-User-Email": ADMIN, "X-User-Admin": "true"}

# Every route this change touches, with the role it must now demand.
ROUTES = [
    ("list_versions", f"/api/projects/{SLUG}/versions", "viewer"),
    ("get_docs", f"/api/projects/{SLUG}/docs", "viewer"),
    ("export_guide", f"/api/projects/{SLUG}/export/guide", "owner"),
    ("export_bundle", f"/api/projects/{SLUG}/export", "owner"),
]
IDS = [name for name, _, _ in ROUTES]
READ_ROUTES = [r for r in ROUTES if r[2] == "viewer"]
EXPORT_ROUTES = [r for r in ROUTES if r[2] == "owner"]


def _deps(func):
    """The dependency callables declared in a route's signature."""
    out = []
    for param in inspect.signature(func).parameters.values():
        default = param.default
        if default is not inspect.Parameter.empty and hasattr(default, "dependency"):
            out.append(default.dependency)
    return out


# ---------------------------------------------------------------------------
# A session that answers from in-memory rows by evaluating the REAL bind
# parameters of the statement it is handed. That is what lets it tell
# `user_email IN (me, team@aiui.local)` apart from `user_email == me` — the
# exact difference between _user_can_see_project and _require_role, and the
# whole reason the team bucket has to be tested.
# ---------------------------------------------------------------------------
def _bound_lower_strings(stmt) -> set[str]:
    try:
        params = stmt.compile().params
    except Exception:  # noqa: BLE001 - not a compilable select
        return set()
    out: set[str] = set()
    for value in params.values():
        # `.in_([a, b])` compiles to ONE expanding bind parameter whose value is
        # the whole list, so it has to be flattened or the team-bucket branch
        # of _user_can_see_project becomes invisible to this fake.
        for item in (value if isinstance(value, (list, tuple, set)) else [value]):
            if isinstance(item, str):
                out.add(item.strip().lower())
    return out


class _Result:
    def __init__(self, row=None, scalar=None):
        self._row = row
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._row

    def scalar(self):
        return self._scalar


class _MatchingSession:
    def __init__(self, members, tasks, supabase, lock_free):
        self.members = list(members)
        self.tasks = list(tasks)
        self.supabase = supabase
        self.lock_free = lock_free

    async def execute(self, stmt, params=None):
        if isinstance(stmt, TextClause):
            # pg_try_advisory_xact_lock
            return _Result(scalar=self.lock_free)
        bound = _bound_lower_strings(stmt)
        entity = None
        try:
            entity = stmt.column_descriptions[0]["entity"]
        except Exception:  # noqa: BLE001
            pass
        if entity is ProjectMember:
            for m in self.members:
                if m.slug.lower() in bound and m.user_email.lower() in bound:
                    return _Result(row=m)
            return _Result()
        if entity is TaskItem:
            for t in self.tasks:
                if (t.built_app_slug or "").lower() in bound \
                        and (t.assignee_email or "").lower() in bound:
                    return _Result(row=t)
            return _Result()
        if entity is ProjectSupabase:
            return _Result(row=self.supabase)
        return _Result()

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _member(email, role, slug=SLUG):
    return ProjectMember(slug=slug, user_email=email, role=role, added_by=ADMIN)


def _task(email, slug=SLUG):
    return TaskItem(
        id=uuid.uuid4(), meeting_id=uuid.uuid4(), action_type="BUILD",
        assignee_name=email.split("@")[0], assignee_email=email,
        description="build me a thing", priority="IMPORTANT", status="completed",
        max_attempts=1, attempt_count=0, conversation_history=[],
        built_app_slug=slug, created_at=datetime.utcnow(),
    )


@pytest.fixture
def project(monkeypatch, tmp_path):
    """Install the fake session plus stand-ins for git, disk and the zipper.

    Only the things the auth decision does NOT depend on are stubbed: the git
    log, the README on disk and app_export. Every membership lookup runs the
    real SQL against the fake rows.
    """
    async def _fake_versions(slug):
        return []
    monkeypatch.setattr(routes_projects, "list_app_versions_core", _fake_versions)

    import app_docs
    monkeypatch.setattr(app_docs, "app_readme_path",
                        lambda slug: tmp_path / slug / "README.md")

    monkeypatch.setattr(routes_projects._app_export, "analyze_app",
                        lambda slug: {"slug": slug})
    monkeypatch.setattr(routes_projects._app_export, "build_deploy_guide",
                        lambda profile: "# Deploy me\n")

    async def _fake_export(slug, *, actor_email, supabase_row):
        out = tmp_path / f"bundle-{uuid.uuid4().hex}"
        out.mkdir()
        zip_path = out / f"{slug}.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("index.html", "<html></html>")
        return zip_path, f"{slug}.zip"
    monkeypatch.setattr(routes_projects._app_export, "export_app", _fake_export)

    def _install(members=(), tasks=(), supabase=None, lock_free=True):
        @asynccontextmanager
        async def _fake_session():
            yield _MatchingSession(members, tasks, supabase, lock_free)
        monkeypatch.setattr(routes_projects, "session", _fake_session)
    return _install


async def _get(path, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, headers=headers)


def _assert_refused_for_the_role(resp, what: str) -> None:
    """403, and specifically a ROLE 403.

    Every one of these callers is refused today too — by `current_admin`, with
    "Admin access required". A bare status assertion would therefore pass
    before the check exists and keep passing if the check were later deleted,
    which is exactly the failure mode this file is meant to prevent.
    """
    assert resp.status_code == 403, f"{what}: expected 403, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert "Admin" not in detail, (
        f"{what}: refused for the old reason (admin header: {detail!r}), not "
        f"for the new one (no role on this project)")


def _cap(monkeypatch, owner, slug):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "s3cr3t-for-tests")
    import edit_capability
    importlib.reload(edit_capability)
    return edit_capability.mint_capability(owner, slug, str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def test_every_named_route_actually_exists():
    """Guards the table above against a rename silently emptying this file."""
    missing = [n for n, _, _ in ROUTES if not hasattr(routes_projects, n)]
    assert not missing, f"renamed or removed: {missing}"


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
def test_the_route_does_not_demand_the_admin_header(name, path, role):
    func = getattr(routes_projects, name)
    assert current_admin_or_capability_for_slug not in _deps(func), (
        f"{name} still falls back to the admin header, so the owner of the app "
        f"cannot reach it")


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
def test_the_route_still_requires_a_signed_in_user(name, path, role):
    """Relaxing the gate must not open it."""
    func = getattr(routes_projects, name)
    assert current_user_or_capability_for_slug in _deps(func), (
        f"{name} lost its authentication")


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
def test_the_role_check_is_in_the_body(name, path, role):
    """The dependency no longer stops anyone, so the body has to."""
    src = inspect.getsource(getattr(routes_projects, name))
    assert "_require_role" in src, f"{name} has no role check at all"
    assert f'"{role}"' in src, f"{name} does not require the {role} role"


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_anonymous_is_refused(project, name, path, role):
    project(members=[_member(OWNER, "owner")])
    r = await _get(path, {})
    assert r.status_code == 401, f"{name} let an anonymous caller in"


# ---------------------------------------------------------------------------
# The property that does not exist today: a signed-in stranger
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_a_signed_in_stranger_is_refused(project, name, path, role):
    """No member row, no task of their own — 403, and specifically a MEMBERSHIP
    403, not "Admin access required" (which would pass for the old reason)."""
    project(members=[_member(OWNER, "owner")], tasks=[_task(OWNER)])
    r = await _get(path, {"X-User-Email": STRANGER})
    _assert_refused_for_the_role(
        r, f"{name} let a signed-in stranger reach an app they have no role on")


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_a_stranger_cannot_ride_the_team_bucket(project, name, path, role):
    """The reason the check had to be WRITTEN rather than moved.

    `_user_can_see_project` matches `user_email IN (email, team@aiui.local)`,
    so for anything in the AIUI team's shared bucket it returns True for every
    signed-in user on earth. Relaxing the dependency without a role check would
    have opened the team's apps to everybody.
    """
    project(members=[_member(TEAM, "owner")], tasks=[_task(TEAM)])
    r = await _get(path, {"X-User-Email": STRANGER})
    _assert_refused_for_the_role(
        r, f"{name} handed a stranger a team-bucket app via _user_can_see_project")


# ---------------------------------------------------------------------------
# What each role may actually do
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_the_owner_can_do_all_four(project, name, path, role):
    """The whole point of the change."""
    project(members=[_member(OWNER, "owner")])
    r = await _get(path, {"X-User-Email": OWNER})
    assert r.status_code == 200, (
        f"the owner of the app still cannot use {name}: "
        f"{r.status_code} {r.text[:200]}")


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_the_creator_with_no_member_row_can_do_all_four(project, name, path, role):
    """_require_role's implicit-owner fallback: the person the build task was
    assigned to owns the app even before the membership backfill runs."""
    project(members=[], tasks=[_task(OWNER)])
    r = await _get(path, {"X-User-Email": OWNER})
    assert r.status_code == 200, f"the app's creator cannot use {name}: {r.text[:200]}"


@pytest.mark.parametrize("name,path,role", READ_ROUTES,
                         ids=[n for n, _, _ in READ_ROUTES])
async def test_a_viewer_can_read_docs_and_versions(project, name, path, role):
    project(members=[_member(VIEWER, "viewer")])
    r = await _get(path, {"X-User-Email": VIEWER})
    assert r.status_code == 200, f"an invited viewer cannot use {name}: {r.text[:200]}"


@pytest.mark.parametrize("name,path,role", EXPORT_ROUTES,
                         ids=[n for n, _, _ in EXPORT_ROUTES])
async def test_a_viewer_cannot_export(project, name, path, role):
    """Export hands over the whole app — source, git history and the Supabase
    config that is otherwise injected at request time and never on disk. Being
    allowed to LOOK at a project is not being allowed to take it."""
    project(members=[_member(VIEWER, "viewer")])
    r = await _get(path, {"X-User-Email": VIEWER})
    _assert_refused_for_the_role(r, f"a viewer downloaded the app via {name}")


@pytest.mark.parametrize("name,path,role", EXPORT_ROUTES,
                         ids=[n for n, _, _ in EXPORT_ROUTES])
async def test_an_editor_cannot_export(project, name, path, role):
    """Same reasoning one rank up: an editor may change the app, not take it."""
    project(members=[_member(EDITOR, "editor")])
    r = await _get(path, {"X-User-Email": EDITOR})
    _assert_refused_for_the_role(r, f"an editor downloaded the app via {name}")


async def test_the_exported_bundle_is_actually_a_zip(project):
    """The relaxation has to leave a working download behind, not just a 200."""
    project(members=[_member(OWNER, "owner")])
    r = await _get(f"/api/projects/{SLUG}/export", {"X-User-Email": OWNER})
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK"


async def test_a_stranger_cannot_take_the_build_lock(project):
    """Authorization has to come BEFORE the advisory lock, or a stranger can
    still probe (and contend for) another user's build lock."""
    project(members=[_member(OWNER, "owner")], lock_free=False)
    r = await _get(f"/api/projects/{SLUG}/export", {"X-User-Email": STRANGER})
    _assert_refused_for_the_role(
        r, "export answered a stranger from the build lock (409) instead of "
           "checking who was asking first")


async def test_a_live_build_still_blocks_the_owners_export(project):
    """The 409 that protects a half-written tree must survive the reorder."""
    project(members=[_member(OWNER, "owner")], lock_free=False)
    r = await _get(f"/api/projects/{SLUG}/export", {"X-User-Email": OWNER})
    assert r.status_code == 409, r.text[:200]


# ---------------------------------------------------------------------------
# Admins keep today's behaviour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_an_admin_on_the_project_keeps_all_four(project, name, path, role):
    """The admin panel still works end to end. The membership row deliberately
    says `viewer`, so the two export routes pass only via the is_admin bypass
    and not because the admin happens to hold the role."""
    project(members=[_member(ADMIN, "viewer")])
    r = await _get(path, ADMIN_HEADERS)
    assert r.status_code == 200, (
        f"the admin project panel lost {name}: {r.status_code} {r.text[:200]}")


@pytest.mark.parametrize("name,path,role", EXPORT_ROUTES,
                         ids=[n for n, _, _ in EXPORT_ROUTES])
async def test_an_admin_can_still_export_a_project_they_are_not_a_member_of(
        project, name, path, role):
    """Today export has no body check at all, so an admin never needed a
    membership row. The new owner check takes `is_admin=` so that stays true."""
    project(members=[], tasks=[])
    r = await _get(path, ADMIN_HEADERS)
    assert r.status_code == 200, (
        f"{name} now demands a membership row from an admin: {r.text[:200]}")


@pytest.mark.parametrize("name,path,role", READ_ROUTES,
                         ids=[n for n, _, _ in READ_ROUTES])
async def test_an_admin_still_reads_a_team_bucket_project(project, name, path, role):
    """versions/docs keep _user_can_see_project as the FIRST of two checks, so
    the admin gate is unchanged — including the team bucket it grants and the
    role it does not require."""
    project(members=[_member(TEAM, "owner")], tasks=[_task(TEAM)])
    r = await _get(path, ADMIN_HEADERS)
    assert r.status_code == 200, f"an admin lost the team bucket on {name}"


@pytest.mark.parametrize("name,path,role", READ_ROUTES,
                         ids=[n for n, _, _ in READ_ROUTES])
async def test_versions_and_docs_do_not_hand_an_admin_a_NEW_bypass(
        project, name, path, role):
    """The other half of "unchanged": today an admin with no way to see the
    project at all is refused by _user_can_see_project, and that must not
    quietly become an admin-sees-everything bypass on the way past. Pinned so
    the widening would have to be a deliberate, separate decision.

    Export is different on purpose — it has no gate for an admin today, so
    taking one away would be the change there.
    """
    project(members=[_member(OWNER, "owner")], tasks=[_task(OWNER)])
    r = await _get(path, ADMIN_HEADERS)
    assert r.status_code == 403, (
        f"{name} widened admin access beyond today's _user_can_see_project gate")


# ---------------------------------------------------------------------------
# The capability path (Visual Editor deep link from Discord/Slack)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_the_capability_path_still_works(project, monkeypatch, name, path, role):
    cap = _cap(monkeypatch, OWNER, SLUG)
    project(members=[_member(OWNER, "owner")])
    r = await _get(path, {"X-Edit-Capability": cap})
    assert r.status_code == 200, (
        f"the visual-editor deep link lost {name}: {r.status_code} {r.text[:200]}")


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_the_capability_is_not_treated_as_admin(project, monkeypatch,
                                                      name, path, role):
    """A capability proves ONE project, never admin: with no live role on it,
    the body must still refuse."""
    cap = _cap(monkeypatch, STRANGER, SLUG)
    project(members=[_member(OWNER, "owner")], tasks=[_task(OWNER)])
    r = await _get(path, {"X-Edit-Capability": cap})
    assert r.status_code == 403, f"{name} waved a capability through as admin"


@pytest.mark.parametrize("name,path,role", ROUTES, ids=IDS)
async def test_a_capability_for_another_slug_is_rejected(project, monkeypatch,
                                                         name, path, role):
    cap = _cap(monkeypatch, OWNER, "some-other-app")
    project(members=[_member(OWNER, "owner")])
    r = await _get(path, {"X-Edit-Capability": cap})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Out of scope, pinned so a later sweep does not quietly take them too
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["list_members", "list_presence",
                                  "clear_presence", "leave_project",
                                  "delete_project"])
def test_the_out_of_scope_routes_are_still_admin_only(name):
    """members / presence / leave / DELETE have no ownership check either, and
    DELETE is destructive. They stay admin-only until each gets its own
    analysis — this pins that decision rather than leaving it to memory."""
    func = getattr(routes_projects, name)
    assert current_admin in _deps(func), (
        f"{name} was relaxed without the ownership analysis it needs")
