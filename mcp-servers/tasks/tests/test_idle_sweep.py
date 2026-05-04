"""Tests for the idle-sweep loop that powers auto-stop of presence-empty
previews. Exercises a single sweep iteration's logic directly so we don't
have to wait the real 30s interval."""
import asyncio
import time
from unittest.mock import patch

import app_runner


async def _run_one_sweep_iteration(is_slug_empty):
    """Mirror the inner block of _idle_sweep_loop without the outer
    while/sleep. Returns nothing — caller asserts on _running and
    _empty_since side effects."""
    now = time.time()
    for slug in list(app_runner._running.keys()):
        if is_slug_empty(slug):
            if slug not in app_runner._empty_since:
                app_runner._empty_since[slug] = now
            elif now - app_runner._empty_since[slug] >= app_runner.PRESENCE_GRACE_SECONDS:
                await app_runner.stop_preview(slug)
                app_runner._empty_since.pop(slug, None)
        else:
            app_runner._empty_since.pop(slug, None)


def _seed_static(slug):
    """Pretend slug is running as a static (no subprocess) preview."""
    app_runner._running[slug] = {
        "slug": slug,
        "kind": "static",
        "port": None,
        "proc": None,
        "started": time.time(),
    }


def _cleanup():
    app_runner._running.clear()
    app_runner._empty_since.clear()


async def test_empty_slug_first_sweep_records_timestamp_only():
    """First sweep iteration where presence is empty must record
    _empty_since but NOT stop yet."""
    _cleanup()
    _seed_static("alpha")
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: True)
        assert "alpha" in app_runner._running, "stop fired too early"
        assert "alpha" in app_runner._empty_since
    finally:
        _cleanup()


async def test_empty_slug_after_grace_is_stopped():
    """After the grace window has elapsed, sweep stops the preview."""
    _cleanup()
    _seed_static("beta")
    # Pretend "beta" has been empty since 200s ago — past the 120s grace.
    app_runner._empty_since["beta"] = time.time() - 200
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: True)
        assert "beta" not in app_runner._running, "auto-stop did not fire"
        assert "beta" not in app_runner._empty_since, "_empty_since not cleared"
    finally:
        _cleanup()


async def test_non_empty_slug_resets_timer():
    """If a user comes back during the grace window, the timer must
    reset so we don't stop on the very next sweep."""
    _cleanup()
    _seed_static("gamma")
    app_runner._empty_since["gamma"] = time.time() - 100  # would fire soon
    try:
        await _run_one_sweep_iteration(is_slug_empty=lambda s: False)
        assert "gamma" in app_runner._running, "stop fired despite presence"
        assert "gamma" not in app_runner._empty_since, "timer did not reset"
    finally:
        _cleanup()


async def test_sweep_constants_are_sensible():
    """Locks in the values from the design doc (Q2 grace = 2 min,
    sweep interval = 30s). Catches accidental changes."""
    assert app_runner.PRESENCE_GRACE_SECONDS == 120
    assert app_runner.SWEEP_INTERVAL_SECONDS == 30


# Test: is_slug_presence_empty helper from routes_projects
import routes_projects


def test_is_slug_presence_empty_true_for_empty_bucket():
    routes_projects._PRESENCE.pop("delta", None)
    assert routes_projects.is_slug_presence_empty("delta") is True


def test_is_slug_presence_empty_false_for_fresh_entry():
    routes_projects._PRESENCE["epsilon"]["u@x"] = {
        "last_seen": time.time(),
        "is_building": False,
    }
    try:
        assert routes_projects.is_slug_presence_empty("epsilon") is False
    finally:
        routes_projects._PRESENCE.pop("epsilon", None)


def test_is_slug_presence_empty_true_when_only_stale_entries():
    """Stale entries (>20s old) should be pruned, leaving the bucket
    effectively empty."""
    routes_projects._PRESENCE["zeta"]["u@x"] = {
        "last_seen": time.time() - 100,  # well past the 20s TTL
        "is_building": False,
    }
    try:
        assert routes_projects.is_slug_presence_empty("zeta") is True
    finally:
        routes_projects._PRESENCE.pop("zeta", None)
