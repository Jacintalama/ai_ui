"""Auth guard on the meetings service.

Why this exists: on 2026-08-03 `GET https://ai-ui.coolestdomain.win/meetings/`
returned 21 meeting records — full transcripts, summaries, attendee names and
Fathom share links — to an unauthenticated caller from the public internet.
`PUT` and `DELETE` were reachable the same way, so anyone could also edit or
erase them.

The gateway strips `x-user-email` from the client request and re-sets it after
JWT validation (api-gateway/main.py:298-309), so a non-empty `X-User-Email`
arriving here is trustworthy. That is the same trust model
`mcp-servers/tasks/routes_schedules.py::_resolve_caller` already relies on.

Transcript ingestion is an external n8n workflow with no user session, so the
write path additionally accepts a shared secret. With the secret unset the
machine path is CLOSED, not open.
"""
import os
import sys
import pathlib

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import main  # noqa: E402

SECRET = "test-ingest-secret"
UUID = "c40991c9-1f09-4d98-8b95-dc4a86893b39"


@pytest.fixture
def client(monkeypatch):
    # No DATABASE_URL: startup logs and returns, _session_maker stays None.
    # Auth must be decided BEFORE the 503, so these tests never need a DB.
    monkeypatch.setattr(main, "_session_maker", None, raising=False)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def ingest(monkeypatch):
    monkeypatch.setenv("MEETINGS_INGEST_SECRET", SECRET)


# --------------------------------------------------------------------------
# The exposure itself: no credentials at all must never reach the data.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/"),
        ("GET", f"/{UUID}"),
        ("POST", "/"),
        ("PUT", f"/{UUID}"),
        ("DELETE", f"/{UUID}"),
    ],
)
def test_anonymous_is_rejected(client, method, path):
    resp = client.request(method, path, json={})
    assert resp.status_code == 403, (
        f"{method} {path} returned {resp.status_code}; anonymous callers must "
        f"get 403. This is the exact hole found in production on 2026-08-03."
    )


def test_health_stays_open(client):
    """Container healthchecks have no JWT. /health must not be gated."""
    assert client.get("/health").status_code == 200


def test_empty_user_email_header_is_not_a_credential(client):
    """The gateway sets X-User-Email to "" for anonymous traffic
    (api-gateway/main.py:423). An empty string must not authenticate."""
    resp = client.get("/", headers={"X-User-Email": ""})
    assert resp.status_code == 403


def test_whitespace_user_email_is_not_a_credential(client):
    resp = client.get("/", headers={"X-User-Email": "   "})
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# Authenticated humans get through the guard (503 = past auth, no DB here).
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/"),
        ("GET", f"/{UUID}"),
        ("POST", "/"),
        ("PUT", f"/{UUID}"),
        ("DELETE", f"/{UUID}"),
    ],
)
def test_signed_in_user_passes_the_guard(client, method, path):
    resp = client.request(
        method, path,
        headers={"X-User-Email": "jacint@example.com"},
        json={"title": "t", "date": "2026-08-03"},
    )
    assert resp.status_code != 403, (
        f"{method} {path} rejected a gateway-validated user"
    )
    assert resp.status_code == 503, (
        f"expected the no-database 503 after passing auth, got {resp.status_code}"
    )


# --------------------------------------------------------------------------
# The machine ingest path: writes only, and closed unless configured.
# --------------------------------------------------------------------------

def test_ingest_secret_allows_create(client, ingest):
    resp = client.post(
        "/",
        headers={"X-Meetings-Ingest-Secret": SECRET},
        json={"title": "Standup", "date": "2026-08-03"},
    )
    assert resp.status_code == 503, "ingest secret should pass auth"


def test_ingest_secret_allows_update(client, ingest):
    resp = client.put(
        f"/{UUID}", headers={"X-Meetings-Ingest-Secret": SECRET}, json={},
    )
    assert resp.status_code == 503


def test_ingest_secret_cannot_read(client, ingest):
    """A transcript writer has no reason to read the archive back."""
    resp = client.get("/", headers={"X-Meetings-Ingest-Secret": SECRET})
    assert resp.status_code == 403


def test_ingest_secret_cannot_delete(client, ingest):
    resp = client.delete(f"/{UUID}", headers={"X-Meetings-Ingest-Secret": SECRET})
    assert resp.status_code == 403


def test_wrong_ingest_secret_is_rejected(client, ingest):
    resp = client.post(
        "/", headers={"X-Meetings-Ingest-Secret": "wrong"}, json={},
    )
    assert resp.status_code == 403


def test_machine_path_is_closed_when_secret_unset(client, monkeypatch):
    """Fail closed. An unset secret must not mean 'any secret works', and must
    not mean 'no secret needed'."""
    monkeypatch.delenv("MEETINGS_INGEST_SECRET", raising=False)
    assert client.post("/", headers={"X-Meetings-Ingest-Secret": ""}, json={}).status_code == 403
    assert client.post("/", json={}).status_code == 403


def test_secret_is_read_at_call_time_not_import_time(client, monkeypatch):
    """The container gets its env at boot, but tests and rotations change it
    later. Reading os.environ at import time would pin a stale value."""
    monkeypatch.setenv("MEETINGS_INGEST_SECRET", "rotated-secret")
    resp = client.post(
        "/",
        headers={"X-Meetings-Ingest-Secret": "rotated-secret"},
        json={"title": "Standup", "date": "2026-08-03"},
    )
    assert resp.status_code == 503
