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


class _FakeElement:
    """A clickable stub. Can be invisible/disabled, can refuse to be clicked,
    and can fire a pageerror the way a real broken handler would."""

    def __init__(self, page, *, visible=True, enabled=True,
                 raises_on_click=None, fires_pageerror=None, navigates_to=None):
        self._page = page
        self._visible = visible
        self._enabled = enabled
        self._raises_on_click = raises_on_click
        self._fires_pageerror = fires_pageerror
        self._navigates_to = navigates_to

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def click(self, **kw):
        self._page.clicks += 1
        if self._raises_on_click is not None:
            raise self._raises_on_click
        if self._fires_pageerror is not None:
            for cb in self._page._listeners.get("pageerror", []):
                cb(self._fires_pageerror)
        if self._navigates_to is not None:
            self._page.url = self._navigates_to


class _FakePage:
    """Minimal page stub: records listeners, fires programmed events on
    goto(), like _FakeWalkPage in test_video_capture.py."""

    def __init__(self, *, status=200, pageerrors=None, console=None,
                 failed_requests=None, goto_error=None,
                 elements=None, selector_error=None):
        self._status = status
        self._pageerrors = pageerrors or []
        self._console = console or []          # list of (type, text)
        self._failed_requests = failed_requests or []  # list of (url, errorText)
        self._goto_error = goto_error
        self._listeners: dict[str, list] = {}
        self._elements = elements or []
        self._selector_error = selector_error
        self.url = "http://preview/app/"
        self.clicks = 0

    async def query_selector_all(self, selector):
        if self._selector_error is not None:
            raise self._selector_error
        return list(self._elements)

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


async def test_smoke_app_fails_open_when_preview_unreachable(monkeypatch):
    # Exercises the real end-to-end fail-open path: browser launches,
    # navigation fails, smoke_app swallows it and returns None.
    #
    # Points at a closed port explicitly. The original form relied on nothing
    # listening on 8210, which holds on a dev laptop but NOT inside the tasks
    # container - there the service itself serves 8210 and answers a fake slug
    # with a real 404, so the test failed in the one environment that matters
    # most. Fixed 2026-07-23; the failure predated the interaction pass.
    import app_smoke
    monkeypatch.setattr(app_smoke, "PREVIEW_BASE_URL", "http://127.0.0.1:9/preview")
    report = await smoke_app("definitely-not-a-real-slug", timeout_ms=3000)
    assert report is None


# --- errors that only appear when you interact ------------------------------
# The smoke check navigated, waited, and reported. Anything that breaks on a
# CLICK was invisible, so an app could pass the check and still be broken for
# the first person who used it. The listeners were already right; the window
# they were open for was too short. See the 2026-07-23 interaction pass.

async def test_click_error_is_caught():
    """The whole point: a handler that throws must be reported."""
    page = _FakePage()
    page._elements = [_FakeElement(page, fires_pageerror="cart is not defined")]
    out = await _smoke_with_page(page, "http://preview/app/")
    assert out is not None, "a broken click handler must fail the smoke"
    assert "cart is not defined" in out


async def test_clean_buttons_still_pass():
    """Clicking healthy buttons must not invent problems."""
    page = _FakePage()
    page._elements = [_FakeElement(page) for _ in range(3)]
    assert await _smoke_with_page(page, "http://preview/app/") is None
    assert page.clicks == 3


async def test_clicking_is_bounded():
    """A page with many buttons must not blow up build time."""
    page = _FakePage()
    page._elements = [_FakeElement(page) for _ in range(50)]
    await _smoke_with_page(page, "http://preview/app/")
    assert page.clicks <= 10, f"clicked {page.clicks} times, should be bounded"


async def test_invisible_and_disabled_buttons_are_skipped():
    page = _FakePage()
    page._elements = [
        _FakeElement(page, visible=False),
        _FakeElement(page, enabled=False),
        _FakeElement(page),
    ]
    await _smoke_with_page(page, "http://preview/app/")
    assert page.clicks == 1, "only the visible, enabled button should be clicked"


async def test_stops_once_the_page_navigates_away():
    """After navigation we are no longer testing this app."""
    page = _FakePage()
    page._elements = [
        _FakeElement(page, navigates_to="http://somewhere-else/"),
        _FakeElement(page),
        _FakeElement(page),
    ]
    await _smoke_with_page(page, "http://preview/app/")
    assert page.clicks == 1, "must stop clicking once the URL changed"


async def test_a_click_that_cannot_execute_is_not_an_app_error():
    """An element detached or covered is a test artifact, not a bug in the app.
    Only what the APP raises (via the pageerror/console listeners) counts."""
    page = _FakePage()
    page._elements = [_FakeElement(page, raises_on_click=RuntimeError("intercepted"))]
    assert await _smoke_with_page(page, "http://preview/app/") is None


async def test_interaction_failure_never_loses_load_time_errors():
    """Fail open: if the interaction pass breaks, still report what load found."""
    page = _FakePage(pageerrors=["boom at load"],
                     selector_error=RuntimeError("selector engine died"))
    out = await _smoke_with_page(page, "http://preview/app/")
    assert out is not None and "boom at load" in out


async def test_page_without_query_selector_all_still_works():
    """Backward compatible: an older page object must not break the smoke."""
    class _Old(_FakePage):
        query_selector_all = None

    page = _Old(pageerrors=["load error"])
    out = await _smoke_with_page(page, "http://preview/app/")
    assert out is not None and "load error" in out
