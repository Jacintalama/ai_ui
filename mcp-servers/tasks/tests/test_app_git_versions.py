"""Owner-scoped git versions + rollback.

Two things under test, both DB-free so they run without Postgres:

1. Route shape: the new /api/aiuibuilder/{slug}/versions (GET) and
   /api/aiuibuilder/{slug}/rollback (POST) routes are registered with the
   right methods and the owner-scoped `current_user` dependency, following
   tests/test_routes_video_shape.py.
2. The extracted cores (list_app_versions_core / rollback_app_core) against
   a real temp git repo. These prove the extraction preserves behavior.
   test_routes_projects.py itself has no DB-gated behavior tests for
   versions/rollback to mirror, so this is the closest thing to that proof
   without needing Postgres.
"""
import os
import subprocess
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi import HTTPException

from auth import current_user
import routes_aiuibuilder as rb
import routes_projects as rp


# ---------------------------------------------------------------------------
# Route shape
# ---------------------------------------------------------------------------

def _route(path: str):
    matches = [r for r in rb.router.routes if r.path == path]
    assert matches, f"no route registered for {path}"
    return matches[0]


def test_versions_route_registered_get():
    r = _route("/api/aiuibuilder/{slug}/versions")
    assert "GET" in r.methods


def test_versions_route_uses_current_user():
    r = _route("/api/aiuibuilder/{slug}/versions")
    assert any(dep.call is current_user for dep in r.dependant.dependencies)


def test_rollback_route_registered_post():
    r = _route("/api/aiuibuilder/{slug}/rollback")
    assert "POST" in r.methods


def test_rollback_route_uses_current_user():
    r = _route("/api/aiuibuilder/{slug}/rollback")
    assert any(dep.call is current_user for dep in r.dependant.dependencies)


# ---------------------------------------------------------------------------
# Extracted cores against a real temp git repo (no DB)
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _commit(repo, slug, content, message):
    app_dir = repo / "apps" / slug
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "index.html").write_text(content)
    _git(repo, "add", f"apps/{slug}/")
    _git(
        repo, "-c", "user.email=setup@test.local", "-c", "user.name=setup",
        "commit", "-m", message,
    )
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A real git repo at tmp_path, with routes_projects._run_git rewired to
    run against it regardless of the cwd argument (or lack of one). This
    mirrors other tests monkeypatching routes_projects.REPO_ROOT, but
    _run_git's `cwd` keyword default is bound at def-time, so patching the
    REPO_ROOT module constant alone would not affect it."""
    _git(tmp_path, "init", "-q")

    real_run_git = rp._run_git

    async def _pinned_run_git(*args, cwd=None):
        return await real_run_git(*args, cwd=str(tmp_path))

    monkeypatch.setattr(rp, "_run_git", _pinned_run_git)
    return tmp_path


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    async def execute(self, *a, **kw):
        return _FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def no_tasks_session(monkeypatch):
    """Stub out routes_projects.session() so list_app_versions_core's task
    cross-reference query runs against an empty result set, with no real
    Postgres connection."""
    monkeypatch.setattr(rp, "session", lambda: _FakeSession())


async def test_rollback_app_core_restores_old_content(git_repo):
    sha_v1 = _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    _commit(git_repo, "alpha", "<h1>v2</h1>", "Build v2")

    result = await rp.rollback_app_core("alpha", sha_v1, "owner@x.com")
    assert result == {"ok": True, "noop": False}
    assert (git_repo / "apps" / "alpha" / "index.html").read_text() == "<h1>v1</h1>"

    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=str(git_repo),
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert log == f"Rollback apps/alpha/ to {sha_v1[:7]}"


async def test_rollback_app_core_invalid_sha_400(git_repo):
    _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    with pytest.raises(HTTPException) as e:
        await rp.rollback_app_core("alpha", "not-a-sha!!", "owner@x.com")
    assert e.value.status_code == 400


async def test_rollback_app_core_unknown_commit_404(git_repo):
    _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    with pytest.raises(HTTPException) as e:
        await rp.rollback_app_core("alpha", "f" * 40, "owner@x.com")
    assert e.value.status_code == 404


async def test_rollback_app_core_dirty_tree_409(git_repo):
    sha_v1 = _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    # Dirty apps/alpha/ without committing.
    (git_repo / "apps" / "alpha" / "index.html").write_text("<h1>uncommitted</h1>")
    with pytest.raises(HTTPException) as e:
        await rp.rollback_app_core("alpha", sha_v1, "owner@x.com")
    assert e.value.status_code == 409


async def test_rollback_app_core_noop_when_already_current(git_repo):
    sha_v1 = _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    result = await rp.rollback_app_core("alpha", sha_v1, "owner@x.com")
    assert result == {"ok": True, "noop": True, "message": "Already at that version"}


async def test_list_app_versions_core_lists_commits_newest_first(git_repo, no_tasks_session):
    _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    sha_v2 = _commit(git_repo, "alpha", "<h1>v2</h1>", "Build v2")

    versions = await rp.list_app_versions_core("alpha")
    assert [v.message for v in versions] == ["Build v2", "Build v1"]
    assert versions[0].sha == sha_v2
    assert versions[0].is_current is True
    assert versions[1].is_current is False
    assert all(v.status == "ok" for v in versions)


async def test_list_app_versions_core_marks_rollback_status(git_repo, no_tasks_session):
    sha_v1 = _commit(git_repo, "alpha", "<h1>v1</h1>", "Build v1")
    _commit(git_repo, "alpha", "<h1>v2</h1>", "Build v2")
    await rp.rollback_app_core("alpha", sha_v1, "owner@x.com")

    versions = await rp.list_app_versions_core("alpha")
    assert versions[0].status == "rollback"
    assert versions[0].is_current is True


async def test_list_app_versions_core_empty_repo_returns_empty_list(git_repo, no_tasks_session):
    # No commits touching apps/alpha/ at all.
    _commit(git_repo, "beta", "<h1>other app</h1>", "Build beta")
    versions = await rp.list_app_versions_core("alpha")
    assert versions == []
