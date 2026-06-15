"""Unit tests for the shared heavy-job lock + RAM/disk guards.

The RAM and disk guards are pure functions over small probes (`_available_ram_mb`
/ `_free_disk_mb`), so they run fully offline once those probes are monkeypatched.

`build_in_flight` and `try_heavy_lock` need a live Postgres session (a SELECT
against `tasks.items` and `pg_*_advisory_lock`), so they are NOT exercised here
with a real DB. We only assert they import cleanly and have the right async
shape; their DB-backed behavior is covered by the worker integration path.
"""
import inspect

from heavy_lock import (
    build_in_flight,
    enough_free_disk,
    enough_free_ram,
    try_heavy_lock,
)


def test_ram_guard_reads_meminfo(monkeypatch):
    monkeypatch.setattr("heavy_lock._available_ram_mb", lambda: 3000)
    assert enough_free_ram(min_mb=1500) is True
    monkeypatch.setattr("heavy_lock._available_ram_mb", lambda: 800)
    assert enough_free_ram(min_mb=1500) is False


def test_disk_guard(monkeypatch):
    monkeypatch.setattr("heavy_lock._free_disk_mb", lambda path: 5000)
    assert enough_free_disk("/x", min_mb=2000) is True
    monkeypatch.setattr("heavy_lock._free_disk_mb", lambda path: 500)
    assert enough_free_disk("/x", min_mb=2000) is False


def test_build_in_flight_is_async():
    # No DB here: just confirm the module imported and the read-only check is a
    # coroutine function (i.e. syntactically sound and awaitable).
    assert inspect.iscoroutinefunction(build_in_flight)


def test_try_heavy_lock_is_async_context_manager():
    # Calling the factory does NOT run the body (asynccontextmanager defers it
    # to __aenter__), so passing a dummy session never touches a database.
    cm = try_heavy_lock(s=None)
    assert hasattr(cm, "__aenter__")
    assert hasattr(cm, "__aexit__")
