"""Regression: GET /api/tasks/<id>/preview/status must return only the
viewed task's slug status, not whichever app happens to be first in the
global _running dict.

Background: when the project moved from a single-slot preview model to
per-slug concurrency (`_running` keyed by slug, 20-port pool), the route
handler in routes_preview.py kept calling `get_status()` with no slug.
get_status(None) falls back to "first slug in _running" for legacy
reasons. So if user A had "testing" running, user B opening "portfolio"
would see status.slug == "testing" and the frontend would block with
"Other app running: testing".

This test exercises the route handler directly to keep it independent of
the DB / auth machinery. The pre-fix behavior leaks the wrong slug; the
post-fix behavior returns the correct task's status (or 'not running').
"""
import time
from unittest.mock import patch
from uuid import UUID

import app_runner
import routes_preview


class _FakeUser:
    pass


class _FakeItem:
    def __init__(self, slug: str):
        self.built_app_slug = slug


async def test_preview_status_does_not_leak_other_apps_slug():
    """When task X's slug is 'beta' and 'alpha' is running, the status
    endpoint for task X must NOT report alpha as running."""
    app_runner._running["alpha"] = {
        "slug": "alpha",
        "kind": "static",
        "port": None,
        "proc": None,
        "started": time.time(),
    }
    try:
        async def fake_get_build_task(task_id):
            return _FakeItem("beta")

        with patch.object(routes_preview, "_get_build_task", fake_get_build_task):
            result = await routes_preview.preview_status(
                task_id=UUID("00000000-0000-0000-0000-000000000001"),
                user=_FakeUser(),
            )

        assert result.get("slug") != "alpha", (
            "Status leaked another app's slug — this is the 'Other app running' bug. "
            f"Got: {result!r}"
        )
        assert result == {"running": False}, (
            f"Expected not-running fallback for unrunning slug 'beta', got {result!r}"
        )
    finally:
        app_runner._running.pop("alpha", None)


async def test_preview_status_returns_correct_slug_when_this_task_is_running():
    """Sanity: when the viewed task IS the running one, status reports it."""
    app_runner._running["gamma"] = {
        "slug": "gamma",
        "kind": "static",
        "port": None,
        "proc": None,
        "started": time.time(),
    }
    try:
        async def fake_get_build_task(task_id):
            return _FakeItem("gamma")

        with patch.object(routes_preview, "_get_build_task", fake_get_build_task):
            result = await routes_preview.preview_status(
                task_id=UUID("00000000-0000-0000-0000-000000000002"),
                user=_FakeUser(),
            )

        assert result.get("slug") == "gamma"
        assert result.get("running") is True
    finally:
        app_runner._running.pop("gamma", None)
