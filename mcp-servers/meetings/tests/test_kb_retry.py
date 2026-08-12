"""A meeting that failed to reach the knowledge base can be pushed again.

Before this, a NULL `kb_file_id` meant "never pushed, and nothing will ever
push it": the only trigger was creating or updating the meeting, and 8
production records sat in that state from 5 May to 2 July 2026.

Why a dedicated endpoint and not a `PUT`
----------------------------------------
`PUT /{id}` already re-dispatches the pipeline, so it "works" as a retry — but
it also re-runs the decision engine, which posts every action item of that
meeting to Discord again. Re-notifying a team about a two-month-old standup to
repair a KB link is not an acceptable side effect, so the retry runs the KB
push only.

Why it answers 202 and not the outcome
--------------------------------------
`/meetings/*` is proxied by api-gateway with a hard `timeout=30.0`
(api-gateway/main.py:317), while `push_to_kb` polls OpenWebUI's processing for
up to 30 x 2s. Waiting inline would 504 on exactly the slow cases and leave the
operator unable to tell whether the push happened — the same ambiguity this
whole change exists to remove. The outcome is durable now, so the honest
answer is "queued", and `GET /{id}` has it.
"""
import sys
import pathlib
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from kb_sync import KbPushError  # noqa: E402
from conftest import Holder, make_record  # noqa: E402

SECRET = "test-ingest-secret"
USER = {"X-User-Email": "jacint@example.com"}


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def failed_meeting(monkeypatch):
    """A row exactly like the 8: no kb_file_id, and now a reason."""
    record = make_record(
        kb_error="KB push failed: HTTP 401 from /api/v1/knowledge/",
        kb_attempted_at=datetime(2026, 5, 5, 12, 0, 0),
    )
    monkeypatch.setattr(main, "_session_maker", Holder(record))
    return record


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_dispatch_kb_retry", lambda record: calls.append(record))
    return calls


# --------------------------------------------------------------------------
# Auth — the same guard as every other write on this service.
# --------------------------------------------------------------------------

def test_anonymous_cannot_trigger_a_retry(client, failed_meeting, dispatched):
    resp = client.post(f"/{failed_meeting.id}/kb-retry")
    assert resp.status_code == 403
    assert dispatched == []


def test_a_signed_in_user_can_trigger_a_retry(client, failed_meeting, dispatched):
    resp = client.post(f"/{failed_meeting.id}/kb-retry", headers=USER)
    assert resp.status_code == 202, resp.text
    assert dispatched == [failed_meeting]


def test_the_ingest_secret_can_trigger_a_retry(client, failed_meeting, dispatched, monkeypatch):
    """Same credential the ingester already uses for POST and PUT."""
    monkeypatch.setenv("MEETINGS_INGEST_SECRET", SECRET)
    resp = client.post(
        f"/{failed_meeting.id}/kb-retry", headers={"X-Meetings-Ingest-Secret": SECRET}
    )
    assert resp.status_code == 202


def test_a_wrong_secret_cannot_trigger_a_retry(client, failed_meeting, dispatched, monkeypatch):
    monkeypatch.setenv("MEETINGS_INGEST_SECRET", SECRET)
    resp = client.post(
        f"/{failed_meeting.id}/kb-retry", headers={"X-Meetings-Ingest-Secret": "wrong"}
    )
    assert resp.status_code == 403
    assert dispatched == []


# --------------------------------------------------------------------------
# Addressing the right meeting.
# --------------------------------------------------------------------------

def test_an_invalid_id_is_rejected(client, failed_meeting, dispatched):
    resp = client.post("/not-a-uuid/kb-retry", headers=USER)
    assert resp.status_code == 400
    assert dispatched == []


def test_an_unknown_meeting_is_404(client, monkeypatch, dispatched):
    monkeypatch.setattr(main, "_session_maker", Holder(None))
    resp = client.post(f"/{uuid.uuid4()}/kb-retry", headers=USER)
    assert resp.status_code == 404
    assert dispatched == []


# --------------------------------------------------------------------------
# Not duplicating what is already there.
# --------------------------------------------------------------------------

def test_a_meeting_already_in_the_kb_is_refused(client, monkeypatch, dispatched):
    """push_to_kb uploads a NEW file every time; OpenWebUI does not dedupe by
    filename. Retrying all 21 rows would leave 13 duplicates in the KB."""
    record = make_record(kb_file_id="file-already-there")
    monkeypatch.setattr(main, "_session_maker", Holder(record))

    resp = client.post(f"/{record.id}/kb-retry", headers=USER)

    assert resp.status_code == 409
    assert "file-already-there" in resp.text
    assert dispatched == []


def test_force_allows_a_deliberate_re_push(client, monkeypatch, dispatched):
    record = make_record(kb_file_id="file-already-there")
    monkeypatch.setattr(main, "_session_maker", Holder(record))

    resp = client.post(f"/{record.id}/kb-retry?force=true", headers=USER)

    assert resp.status_code == 202
    assert dispatched == [record]


def test_no_database_is_503(client, monkeypatch, dispatched):
    monkeypatch.setattr(main, "_session_maker", None)
    resp = client.post(f"/{uuid.uuid4()}/kb-retry", headers=USER)
    assert resp.status_code == 503


# --------------------------------------------------------------------------
# What the retry actually does.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_successful_retry_records_the_file_id(monkeypatch):
    record = make_record(kb_error="HTTP 401 from /api/v1/knowledge/")
    monkeypatch.setattr(main, "_session_maker", Holder(record))

    async def _ok(*_a, **_kw):
        return "file-new"

    monkeypatch.setattr(main, "push_to_kb", _ok)

    await main._guarded_kb_push(record)

    assert record.kb_file_id == "file-new"
    assert record.kb_error is None
    assert record.kb_attempted_at is not None


@pytest.mark.asyncio
async def test_a_failed_retry_records_the_new_reason(monkeypatch):
    """A retry that fails must not leave the previous reason in place, or the
    operator debugs a stale error."""
    record = make_record(kb_error="HTTP 401 from /api/v1/knowledge/")
    monkeypatch.setattr(main, "_session_maker", Holder(record))

    async def _boom(*_a, **_kw):
        raise KbPushError("KB push failed for meeting-x.md: HTTP 503 from /api/v1/files/: {}")

    monkeypatch.setattr(main, "push_to_kb", _boom)

    await main._guarded_kb_push(record)

    assert "503" in record.kb_error
    assert record.kb_file_id is None


@pytest.mark.asyncio
async def test_the_retry_does_not_re_run_the_decision_engine(monkeypatch):
    """Re-notifying Discord about a two-month-old meeting's action items is
    not an acceptable price for repairing a KB link."""
    record = make_record()
    monkeypatch.setattr(main, "_session_maker", Holder(record))

    async def _ok(*_a, **_kw):
        return "file-new"

    async def _must_not_run(**_kwargs):
        raise AssertionError("the retry re-ran the decision engine")

    monkeypatch.setattr(main, "push_to_kb", _ok)
    monkeypatch.setattr(main, "process_action_items", _must_not_run)
    monkeypatch.setattr(main, "process_transcript", _must_not_run)

    await main._guarded_kb_push(record)

    assert record.kb_file_id == "file-new"


@pytest.mark.asyncio
async def test_a_crashing_retry_never_raises_into_the_event_loop(monkeypatch):
    record = make_record()

    class _BrokenMaker:
        def __call__(self):
            raise RuntimeError("connection pool exhausted")

    monkeypatch.setattr(main, "_session_maker", _BrokenMaker())

    def _crash(**_kwargs):
        raise TypeError("filename built from a None date")

    monkeypatch.setattr(main, "format_meeting_markdown", _crash)

    await main._guarded_kb_push(record)  # must simply return
