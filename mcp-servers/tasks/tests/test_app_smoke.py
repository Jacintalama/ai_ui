"""Unit tests for the real-browser smoke check. _smoke_with_page is tested
against a fake page object (mirrors _FakeWalkPage in test_video_capture.py)
so no real browser is needed for the core logic. smoke_app() itself is
exercised once end to end against an unreachable host to prove the outer
fail-open path works with a real (local) Chromium."""
from app_smoke import _smoke_with_page, smoke_app


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status


class _FakeConsoleMsg:
    def __init__(self, type_, text):
        self.type = type_
        self.text = text


class _FakeRequest:
    def __init__(self, url, error_text):
        self.url = url
        self.failure = {"errorText": error_text} if error_text else None


class _FakePage:
    """Minimal page stub: records listeners, fires programmed events on
    goto(), like _FakeWalkPage in test_video_capture.py."""

    def __init__(self, *, status=200, pageerrors=None, console=None,
                 failed_requests=None, goto_error=None):
        self._status = status
        self._pageerrors = pageerrors or []
        self._console = console or []          # list of (type, text)
        self._failed_requests = failed_requests or []  # list of (url, errorText)
        self._goto_error = goto_error
        self._listeners: dict[str, list] = {}

    def on(self, event, callback):
        self._listeners.setdefault(event, []).append(callback)

    async def goto(self, url, **kw):
        if self._goto_error is not None:
            raise self._goto_error
        for err in self._pageerrors:
            for cb in self._listeners.get("pageerror", []):
                cb(err)
        for type_, text in self._console:
            for cb in self._listeners.get("console", []):
                cb(_FakeConsoleMsg(type_, text))
        for url_, err_text in self._failed_requests:
            for cb in self._listeners.get("requestfailed", []):
                cb(_FakeRequest(url_, err_text))
        return _FakeResponse(self._status)

    async def wait_for_timeout(self, ms):
        return None


async def test_clean_page_returns_none():
    page = _FakePage(status=200)
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is None


async def test_console_error_is_reported():
    page = _FakePage(console=[("error", "TypeError: foo is not a function")])
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is not None
    assert "console.error" in report
    assert "TypeError: foo is not a function" in report


async def test_console_log_is_not_reported():
    page = _FakePage(console=[("log", "just some info")])
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is None


async def test_pageerror_is_reported():
    page = _FakePage(pageerrors=["Uncaught ReferenceError: x is not defined"])
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is not None
    assert "pageerror" in report
    assert "ReferenceError" in report


async def test_failed_request_is_reported():
    page = _FakePage(failed_requests=[("http://localhost:8210/app.js", "net::ERR_ABORTED")])
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is not None
    assert "request failed" in report
    assert "app.js" in report


async def test_non_200_main_response_is_reported():
    page = _FakePage(status=500)
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is not None
    assert "main response status 500" in report


async def test_report_is_deduped_and_capped():
    page = _FakePage(console=[("error", "same error")] * 20)
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is not None
    lines = report.split("\n")
    assert len(lines) == 1


async def test_goto_exception_fails_open():
    page = _FakePage(goto_error=RuntimeError("connection refused"))
    report = await _smoke_with_page(page, "http://localhost:8210/tasks/preview-app/x/")
    assert report is None


async def test_smoke_app_fails_open_when_preview_unreachable():
    # Nothing is listening on 8210 in the test environment, so this
    # exercises the real end-to-end fail-open path (browser launches,
    # navigation fails, smoke_app swallows it and returns None).
    report = await smoke_app("definitely-not-a-real-slug", timeout_ms=3000)
    assert report is None
