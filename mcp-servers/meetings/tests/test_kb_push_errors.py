"""A KB push that does not happen has to say why.

Why this exists: 8 of 21 production meeting records (5 May - 2 July 2026) have
a NULL `kb_file_id`. `push_to_kb` returned `None` for every one of them, and
`None` carries no reason, so two months later the trigger is unrecoverable —
Loki retains 168h and the container had restarted. A 401 from an expired
OpenWebUI key and a 500 from the embedding worker were, to the caller, the
same value.

The reason has to survive the call. That is what makes the failure
diagnosable at all, and it is what `_process_and_push` stores in the record.
"""
import sys
import pathlib

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import kb_sync  # noqa: E402

URL = "https://ai-ui.coolestdomain.win"
KEY = "sk-test-key"


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_client(handler):
    """Build a factory that swaps httpx's network for `handler`.

    push_to_kb constructs its own AsyncClient, so the seam is the class
    itself. The real request/response plumbing still runs.
    """
    def factory(*_args, **kwargs):
        kwargs.pop("timeout", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(**kwargs)
    return factory


def _happy_path(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v1/knowledge/":
        return httpx.Response(200, json=[{"id": "kb-1", "name": kb_sync.KB_NAME}])
    if path == "/api/v1/files/":
        return httpx.Response(200, json={"id": "file-abc"})
    if path.endswith("/process/status"):
        return httpx.Response(200, json={"status": "completed"})
    if path == "/api/v1/knowledge/kb-1/file/add":
        return httpx.Response(200, json={})
    raise AssertionError(f"unexpected request to {path}")


@pytest.mark.asyncio
async def test_success_returns_the_file_id(monkeypatch):
    monkeypatch.setattr(kb_sync.httpx, "AsyncClient", _mock_client(_happy_path))
    file_id = await kb_sync.push_to_kb(URL, KEY, "meeting-2026-05-05-x.md", "# x")
    assert file_id == "file-abc"


@pytest.mark.asyncio
async def test_failure_reason_names_the_http_status(monkeypatch):
    """The single most useful fact about the 8 lost rows would have been the
    status code. An expired key is a 401; a broken KB is a 5xx."""
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Not authenticated"})

    monkeypatch.setattr(kb_sync.httpx, "AsyncClient", _mock_client(unauthorized))

    with pytest.raises(kb_sync.KbPushError) as exc_info:
        await kb_sync.push_to_kb(URL, KEY, "meeting-2026-05-05-x.md", "# x")

    reason = str(exc_info.value)
    assert "401" in reason, f"reason must name the status code, got: {reason}"


@pytest.mark.asyncio
async def test_failure_reason_names_the_step_that_failed(monkeypatch):
    """Upload succeeded, linking to the KB did not — a very different repair
    from 'the key is dead'. The reason has to tell them apart."""
    def add_fails(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/knowledge/kb-1/file/add":
            return httpx.Response(500, json={"detail": "boom"})
        return _happy_path(request)

    monkeypatch.setattr(kb_sync.httpx, "AsyncClient", _mock_client(add_fails))

    with pytest.raises(kb_sync.KbPushError) as exc_info:
        await kb_sync.push_to_kb(URL, KEY, "meeting-2026-05-05-x.md", "# x")

    reason = str(exc_info.value)
    assert "500" in reason
    assert "/file/add" in reason, f"reason must name the failing step, got: {reason}"


@pytest.mark.asyncio
async def test_missing_api_key_is_a_failure_not_a_silent_skip(monkeypatch):
    """An unset key produced exactly the same NULL as a network error, and
    'skipping KB push' at WARNING was the only trace."""
    with pytest.raises(kb_sync.KbPushError) as exc_info:
        await kb_sync.push_to_kb(URL, "", "meeting-2026-05-05-x.md", "# x")

    assert "OPENWEBUI_API_KEY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transport_error_is_reported_with_its_type(monkeypatch):
    """A DNS failure or connect timeout never reaches a status code."""
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(kb_sync.httpx, "AsyncClient", _mock_client(refused))

    with pytest.raises(kb_sync.KbPushError) as exc_info:
        await kb_sync.push_to_kb(URL, KEY, "meeting-2026-05-05-x.md", "# x")

    assert "ConnectError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reason_is_bounded(monkeypatch):
    """OpenWebUI can return an HTML error page. The reason is written to a DB
    column and read by a human; it must not carry a whole page."""
    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="x" * 50_000)

    monkeypatch.setattr(kb_sync.httpx, "AsyncClient", _mock_client(huge))

    with pytest.raises(kb_sync.KbPushError) as exc_info:
        await kb_sync.push_to_kb(URL, KEY, "meeting-2026-05-05-x.md", "# x")

    assert len(str(exc_info.value)) < 1000
