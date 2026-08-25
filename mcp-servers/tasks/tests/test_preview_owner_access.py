"""A user must be able to preview and read the files of their OWN app.

Reported from the App Builder with a regular account on 2026-08-20:

    Could not load files: 403 {"detail":"Admin access required"}
    Preview couldn't auto-start: 403 {"detail":"Admin access required"}

The build itself now works, so the user could create an app and never look at
it — the pane showed "App is not running" with no way to start it.

Every route in routes_preview.py demanded the admin header, and — unlike
list_tasks/get_task/execute, where the gate was redundant — **none of them
checked ownership at all**. `_get_build_task` only asserts the task exists and
has a slug. So relaxing the dependency alone would have let any signed-in user
read any app's source: `read_file` returns `target.read_text()`.

That makes this the same shape as the export routes (d7bc1a465): the check has
to be WRITTEN, then the gate relaxed. It is not a one-line swap, and the tests
below exist to stop it being treated as one.

Roles follow the export precedent — reads are viewer-level, actions that mutate
shared state are higher. `start`/`stop` drive a single global preview server
(`stop_preview()` takes no slug), so they require editor rather than viewer.
"""
import inspect

import pytest

import routes_preview as rp
from auth import (AdminUser, CurrentUser, current_admin,
                  current_admin_or_capability, current_user_or_capability)

READ_ROUTES = ["list_files", "read_file", "preview_status"]
ACTION_ROUTES = ["preview_start", "preview_stop"]
ALL_ROUTES = READ_ROUTES + ACTION_ROUTES


def _deps(func):
    out = []
    for p in inspect.signature(func).parameters.values():
        d = p.default
        if d is not inspect.Parameter.empty and hasattr(d, "dependency"):
            out.append(d.dependency)
    return out


def test_every_named_route_exists():
    """Guards the lists above against a rename silently emptying this file."""
    missing = [n for n in ALL_ROUTES if not hasattr(rp, n)]
    assert not missing, f"renamed or removed: {missing}"


@pytest.mark.parametrize("name", ALL_ROUTES)
def test_the_route_does_not_demand_the_admin_header(name):
    """The 403 the user actually hit."""
    deps = _deps(getattr(rp, name))
    assert current_admin_or_capability not in deps, (
        f"{name} still falls back to the admin header, so a regular user "
        f"cannot preview or read their own app")
    assert current_admin not in deps, f"{name} still requires admin"


@pytest.mark.parametrize("name", ALL_ROUTES)
def test_the_route_still_requires_a_signed_in_user(name):
    """Relaxing the gate must not open it."""
    assert current_user_or_capability in _deps(getattr(rp, name)), (
        f"{name} lost its authentication")


@pytest.mark.parametrize("name", ALL_ROUTES)
def test_the_route_now_checks_ownership_itself(name):
    """THE the point. These had no ownership check of any kind, so the admin
    header was the only thing standing between a signed-in stranger and
    `read_file` returning another user's source."""
    src = inspect.getsource(getattr(rp, name))
    assert "_owned_build_task" in src, (
        f"{name} has no ownership check; opening its gate would expose every "
        f"user's app to every signed-in account")
    # And the shared helper must be the thing that actually enforces it.
    helper = inspect.getsource(rp._owned_build_task)
    assert "_require_role" in helper, (
        "_owned_build_task does not call _require_role, so every route that "
        "trusts it is unprotected")


@pytest.mark.parametrize("name", READ_ROUTES)
def test_reads_are_viewer_level(name):
    src = inspect.getsource(getattr(rp, name))
    assert "viewer" in src, f"{name} should be viewer-level (a pure read)"
    assert "editor" not in src, f"{name} is a read and should not need editor"


@pytest.mark.parametrize("name", ACTION_ROUTES)
def test_starting_or_stopping_the_preview_needs_editor(name):
    """`stop_preview()` takes no slug — there is ONE preview server for the
    whole service, so start/stop mutate state shared with everyone else."""
    src = inspect.getsource(getattr(rp, name))
    assert "editor" in src, (
        f"{name} drives a shared singleton and should need editor, not viewer")


def test_admins_keep_their_bypass():
    """Support must still be able to look at a user's app."""
    helper = inspect.getsource(rp._owned_build_task)
    assert "is_admin" in helper, (
        "_owned_build_task no longer forwards is_admin, so an admin cannot "
        "look at a user's app for support")
