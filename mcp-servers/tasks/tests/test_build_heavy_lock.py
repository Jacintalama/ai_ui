"""Builds run inside the shared heavy-job advisory lock (render/build mutual
exclusion).

Task 1.4 of the AI video generator plan: the existing build path must hold the
single global ``heavy_job`` lock for exactly the span of the agent
subprocess/SSH run so a build and a video render can never run at once on the
shared box.

These tests are fully offline. The real lock SELECTs ``pg_advisory_lock`` and so
needs a live Postgres (covered by the integration path); here we monkeypatch the
DB session, the executor, and ``heavy_lock`` itself with a tracking stand-in to
assert the *wiring*: the executor runs strictly between lock-acquire and
lock-release, and the lock is released even when the executor blows up.
"""
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import routes_execution as rx
from heavy_lock import heavy_lock, try_heavy_lock


# --- offline doubles -------------------------------------------------------

class _FakeResult:
    def scalar_one_or_none(self):
        return SimpleNamespace(built_app_slug="test-slug")

    def scalar(self):
        return 1


class _FakeSession:
    async def execute(self, *a, **k):
        return _FakeResult()

    async def commit(self):
        return None


def _fake_session_factory():
    @asynccontextmanager
    async def _cm():
        yield _FakeSession()

    return _cm()


def _tracking_heavy_lock(events):
    @asynccontextmanager
    async def _hl(s):
        events.append("LOCK_ENTER")
        try:
            yield
        finally:
            events.append("LOCK_EXIT")

    return _hl


class _Exec:
    """Async-generator executor stub that records each chunk it produces and can
    optionally raise after a given chunk index."""

    def __init__(self, events, chunks, raise_after=None):
        self._events = events
        self._chunks = chunks
        self._raise_after = raise_after

    async def run(self, prompt, slug=None, execution_id="", user_jwt=None, schedule_id=None):
        for i, c in enumerate(self._chunks):
            self._events.append("CHUNK")
            yield c
            if self._raise_after is not None and i == self._raise_after:
                raise RuntimeError("boom")

    async def stop(self):
        return None


# --- tests -----------------------------------------------------------------

def test_heavy_lock_is_async_context_manager():
    # Factory defers the body to __aenter__ (asynccontextmanager), so calling it
    # with a dummy session never touches a database — mirrors the try_heavy_lock
    # shape test. The blocking helper must be distinct from the non-blocking one.
    cm = heavy_lock(s=None)
    assert hasattr(cm, "__aenter__")
    assert hasattr(cm, "__aexit__")
    assert heavy_lock is not try_heavy_lock


async def test_stream_claude_runs_executor_inside_heavy_lock(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(rx, "session", _fake_session_factory)
    monkeypatch.setattr(rx, "heavy_lock", _tracking_heavy_lock(events))
    monkeypatch.setattr(rx, "get_executor", lambda: _Exec(events, ["a", "b"]))

    out = await rx._stream_claude("prompt", uuid.uuid4(), uuid.uuid4())

    assert out == "ab"
    # The heavy subprocess must run strictly between acquire and release.
    assert events == ["LOCK_ENTER", "CHUNK", "CHUNK", "LOCK_EXIT"]


async def test_stream_claude_releases_lock_on_executor_failure(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(rx, "session", _fake_session_factory)
    monkeypatch.setattr(rx, "heavy_lock", _tracking_heavy_lock(events))
    monkeypatch.setattr(rx, "get_executor", lambda: _Exec(events, ["a"], raise_after=0))

    with pytest.raises(RuntimeError):
        await rx._stream_claude("prompt", uuid.uuid4(), uuid.uuid4())

    # Acquired first, and released despite the failure (try/finally guarantee).
    assert events[0] == "LOCK_ENTER"
    assert events[-1] == "LOCK_EXIT"
