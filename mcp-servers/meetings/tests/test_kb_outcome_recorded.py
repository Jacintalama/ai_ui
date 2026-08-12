"""The background push has to leave the outcome behind, success or failure.

`_process_and_push` is fired as a bare `asyncio.create_task(...)`. Nothing
awaits it and nothing holds a reference to it, so an exception raised inside is
delivered to the event loop's exception handler and then gone. It wrote
`kb_file_id` only on success and recorded nothing at all on failure, which is
why 8 records (5 May - 2 July 2026) look identical to records that were never
pushed, and why the cause was still unknown two months later.

These tests drive the outcome — either branch — into the row.
"""
import asyncio
import sys
import pathlib
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from kb_sync import KbPushError  # noqa: E402
from models import MeetingRecord  # noqa: E402


# --------------------------------------------------------------------------
# A session maker over a single in-memory row. There is no Postgres here, and
# the behaviour under test is "what gets written", not SQL.
# --------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, record):
        self._record = record

    def scalar_one_or_none(self):
        return self._record


class _FakeSession:
    def __init__(self, holder):
        self.holder = holder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, _stmt):
        return _FakeResult(self.holder.record)

    def add(self, record):
        self.holder.record = record

    async def commit(self):
        self.holder.commits += 1

    async def refresh(self, record):
        record.id = record.id or uuid.uuid4()
        record.created_at = record.created_at or datetime.utcnow()
        record.updated_at = record.updated_at or datetime.utcnow()


class _Holder:
    def __init__(self, record=None):
        self.record = record
        self.commits = 0

    def __call__(self):
        return _FakeSession(self)


def _record(**kwargs):
    values = {
        "id": uuid.uuid4(),
        "title": "Standup",
        "date": "2026-05-05",
        "summary": "already summarised, so the AI step is skipped",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    values.update(kwargs)
    return MeetingRecord(**values)


@pytest.fixture
def quiet_decision_engine(monkeypatch):
    """The decision engine posts to Discord; it is not what is under test."""
    async def _noop(**_kwargs):
        return {"processed": 0, "results": []}

    monkeypatch.setattr(main, "process_action_items", _noop)


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failed_push_is_written_to_the_record(monkeypatch, quiet_decision_engine):
    record = _record()
    holder = _Holder(record)
    monkeypatch.setattr(main, "_session_maker", holder)

    async def _boom(*_a, **_kw):
        raise KbPushError("KB push failed for meeting-x.md: HTTP 401 from /api/v1/knowledge/: {}")

    monkeypatch.setattr(main, "push_to_kb", _boom)

    await main._guarded_process_and_push(record)

    assert record.kb_error is not None, "a failed push left no trace — this is the bug"
    assert "401" in record.kb_error
    assert record.kb_attempted_at is not None, "no record of when it was tried"
    assert record.kb_file_id is None


@pytest.mark.asyncio
async def test_an_unexpected_crash_is_recorded_not_swallowed(monkeypatch, quiet_decision_engine):
    """A bare create_task swallows anything raised inside it. A NameError in
    this function would have been invisible in exactly the same way."""
    record = _record()
    holder = _Holder(record)
    monkeypatch.setattr(main, "_session_maker", holder)

    def _crash(**_kwargs):
        raise TypeError("filename built from a None date")

    monkeypatch.setattr(main, "format_meeting_markdown", _crash)

    await main._guarded_process_and_push(record)

    assert record.kb_error is not None
    assert "TypeError" in record.kb_error
    assert "None date" in record.kb_error


@pytest.mark.asyncio
async def test_the_guard_never_raises_into_the_event_loop(monkeypatch, quiet_decision_engine):
    """If the database is the thing that is broken, recording the failure
    fails too. That must not turn into a second unhandled task exception."""
    record = _record()

    class _BrokenMaker:
        def __call__(self):
            raise RuntimeError("connection pool exhausted")

    monkeypatch.setattr(main, "_session_maker", _BrokenMaker())

    async def _boom(*_a, **_kw):
        raise KbPushError("HTTP 500")

    monkeypatch.setattr(main, "push_to_kb", _boom)

    await main._guarded_process_and_push(record)  # must simply return


@pytest.mark.asyncio
async def test_the_recorded_reason_is_bounded(monkeypatch, quiet_decision_engine):
    record = _record()
    holder = _Holder(record)
    monkeypatch.setattr(main, "_session_maker", holder)

    async def _boom(*_a, **_kw):
        raise KbPushError("y" * 20_000)

    monkeypatch.setattr(main, "push_to_kb", _boom)

    await main._guarded_process_and_push(record)

    assert len(record.kb_error) <= main.MAX_KB_ERROR_CHARS


# --------------------------------------------------------------------------
# Success
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_successful_push_clears_the_previous_failure(monkeypatch, quiet_decision_engine):
    """Otherwise a repaired meeting still reads as broken forever."""
    record = _record(kb_error="HTTP 401 from /api/v1/knowledge/", kb_attempted_at=datetime(2026, 5, 5))
    holder = _Holder(record)
    monkeypatch.setattr(main, "_session_maker", holder)

    async def _ok(*_a, **_kw):
        return "file-repaired"

    monkeypatch.setattr(main, "push_to_kb", _ok)

    await main._guarded_process_and_push(record)

    assert record.kb_file_id == "file-repaired"
    assert record.kb_error is None, "a fixed record still advertises the old failure"
    assert record.kb_attempted_at > datetime(2026, 5, 5)


# --------------------------------------------------------------------------
# Wiring: the endpoints must dispatch the guarded pipeline, not the bare one.
# `python -c "import main"` cannot catch this.
# --------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_dispatch_kb_pipeline", lambda record: calls.append(record))
    return calls


def test_create_dispatches_the_guarded_pipeline(client, monkeypatch, dispatched):
    monkeypatch.setattr(main, "_session_maker", _Holder())
    resp = client.post(
        "/",
        headers={"X-User-Email": "jacint@example.com"},
        json={"title": "Standup", "date": "2026-05-05"},
    )
    assert resp.status_code == 201
    assert len(dispatched) == 1


def test_update_dispatches_the_guarded_pipeline(client, monkeypatch, dispatched):
    record = _record()
    monkeypatch.setattr(main, "_session_maker", _Holder(record))
    resp = client.put(
        f"/{record.id}",
        headers={"X-User-Email": "jacint@example.com"},
        json={"title": "Standup (edited)"},
    )
    assert resp.status_code == 200
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_the_dispatcher_runs_the_guarded_coroutine(monkeypatch):
    """The whole point: whatever the endpoints schedule must be the version
    that cannot lose an exception. And the task must be held onto — asyncio
    keeps only a weak reference, so a fire-and-forget task can be garbage
    collected mid-flight and disappear with no trace either."""
    seen = []

    async def _fake_guard(record):
        seen.append(record)

    monkeypatch.setattr(main, "_guarded_process_and_push", _fake_guard)

    record = _record()
    main._dispatch_kb_pipeline(record)

    assert main._BACKGROUND_TASKS, "nothing holds the task; it may be collected mid-flight"
    await asyncio.gather(*list(main._BACKGROUND_TASKS))
    assert seen == [record], "the dispatched coroutine was not the guarded one"

    await asyncio.sleep(0)
    assert not main._BACKGROUND_TASKS, "finished tasks are never released"


# --------------------------------------------------------------------------
# Visibility: an operator reads the API, not the database.
# --------------------------------------------------------------------------

def test_the_api_shows_the_failure(client, monkeypatch):
    record = _record(
        kb_error="KB push failed for meeting-x.md: HTTP 401 from /api/v1/knowledge/",
        kb_attempted_at=datetime(2026, 5, 5, 12, 0, 0),
    )
    monkeypatch.setattr(main, "_session_maker", _Holder(record))

    body = client.get(f"/{record.id}", headers={"X-User-Email": "jacint@example.com"}).json()

    assert "401" in (body.get("kb_error") or ""), (
        "GET /{id} hides the failure; an operator would still see only a null kb_file_id"
    )
    assert body.get("kb_attempted_at") is not None
