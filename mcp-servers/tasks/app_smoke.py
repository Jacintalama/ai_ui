"""Real-browser smoke check for a freshly built app's preview.

Loads the app's INTERNAL preview URL (the tasks service serves static apps
itself at /tasks/preview-app/<slug>/, see main.py's "Per-slug preview
hosting" section) with headless Playwright chromium and looks for concrete
signs the page failed to load: a non-200 main response, uncaught page
errors, console.error messages, and failed resource loads.

No FastAPI imports here, mirroring video_capture.py; routes_execution.py
calls smoke_app() directly.

Fails OPEN everywhere: a missing engine, an unreachable preview, or any
other internal failure returns None (nothing to report) with a logged
warning, so an outage in the checker itself can never block a build.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The tasks service hosts static preview builds on itself (uvicorn on
# 8210); Caddy proxies /tasks/preview-app/* into this same container.
PREVIEW_BASE_URL = "http://localhost:8210/tasks/preview-app"

_MAX_REPORT_LINES = 10
_MAX_MESSAGE_LEN = 200
_SETTLE_MS = 2500


def _truncate(text: str, limit: int = _MAX_MESSAGE_LEN) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit] + "..."
    return text


async def _smoke_with_page(page, url: str, *, timeout_ms: int = 15000) -> str | None:
    """Drive an already-created Playwright page through the smoke check.

    Separated from smoke_app() so tests can inject a fake page instead of a
    real browser (mirrors video_capture._walk_with_page)."""
    issues: list[str] = []

    def _on_pageerror(err) -> None:
        try:
            issues.append(f"- pageerror: {_truncate(str(err))}")
        except Exception:  # noqa: BLE001 - a listener must never raise
            pass

    def _on_console(msg) -> None:
        try:
            if getattr(msg, "type", "") == "error":
                issues.append(f"- console.error: {_truncate(getattr(msg, 'text', ''))}")
        except Exception:  # noqa: BLE001
            pass

    def _on_requestfailed(request) -> None:
        try:
            failure = getattr(request, "failure", None)
            reason = failure.get("errorText") if isinstance(failure, dict) else str(failure)
            issues.append(
                f"- request failed: {_truncate(getattr(request, 'url', ''))} ({_truncate(str(reason))})"
            )
        except Exception:  # noqa: BLE001
            pass

    # Listeners registered before goto so nothing fired during navigation
    # itself (redirects, early errors) is missed.
    page.on("pageerror", _on_pageerror)
    page.on("console", _on_console)
    page.on("requestfailed", _on_requestfailed)

    try:
        response = await page.goto(url, wait_until="load", timeout=timeout_ms)
    except Exception as e:  # noqa: BLE001 - preview unreachable: fail open
        logger.warning("app_smoke: preview unreachable at %s: %s", url, e)
        return None

    if response is None:
        issues.insert(0, "- http: no response for the main request")
    else:
        status = getattr(response, "status", 200)
        if status != 200:
            issues.insert(0, f"- http: main response status {status}")

    await page.wait_for_timeout(_SETTLE_MS)

    if not issues:
        return None

    deduped: list[str] = []
    seen: set[str] = set()
    for item in issues:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return "\n".join(deduped[:_MAX_REPORT_LINES])


async def smoke_app(slug: str, *, timeout_ms: int = 15000) -> str | None:
    """Load apps/<slug>/'s internal preview and report concrete load errors.

    Returns a deduped report string (max ~10 lines, each `- <source>:
    <message>`), or None when the page loads clean. Never raises: ANY
    internal failure (missing engine, browser launch error, preview
    unreachable, navigation timeout, ...) is logged as a warning and
    treated as "nothing to report" so a checker outage can never block a
    build."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("app_smoke: playwright not available, skipping smoke check for %s", slug)
        return None

    url = f"{PREVIEW_BASE_URL}/{slug}/"

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                context = await browser.new_context()
                page = await context.new_page()
                return await _smoke_with_page(page, url, timeout_ms=timeout_ms)
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001 - fail open on any checker failure
        logger.warning("app_smoke: smoke check failed for %s: %s", slug, e)
        return None
