"""A glimpse of each app, on its own card.

The Built apps list described every project in words and showed none of them.
Twenty landing pages wore the same layout, so telling a keyboard site from an
aircon site meant reading the prompt underneath. A picture of the page answers
that at a glance.

The picture comes from a real browser, and that is the constraint the design
bends around. This box has roughly 1.2GB available and Chromium wants a few
hundred MB of it, so a screenshot is never taken while somebody is waiting for
a page. It is captured once, cached on disk beside the app, and served as a
static file. The card asks for that file and shows nothing if it is not there
yet, then picks it up on the next load.

Captures are serialised through one lock, because a list of twenty cards fires
twenty requests at once and twenty Chromiums would take the box down.
"""
import asyncio
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: Wide enough to show a hero and its layout, small enough that twenty of them
#: on one page are not a megabyte each.
VIEWPORT = {"width": 1280, "height": 800}
#: Captured at half scale as JPEG. The same page is 956KB as a full-scale PNG
#: and 24KB this way, and it is displayed 132px tall in a card: forty times the
#: bytes for detail nobody can see.
DEVICE_SCALE = 0.5
JPEG_QUALITY = 72
CAPTURE_TIMEOUT_MS = 15000
#: Fonts and any entrance animation need a beat before the paint is worth
#: keeping, the same wait the template preview generator uses.
SETTLE_MS = 1200

#: Directories that churn without the page changing. Watching them would burn a
#: Chromium launch to produce a screenshot identical to the cached one.
IGNORED_DIRS = {".git", ".thumb", ".video", "node_modules", "__pycache__",
                ".next", "dist", "build", ".vercel"}

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

#: Serialises captures and de-duplicates concurrent requests for one app.
_lock = asyncio.Lock()
_in_flight = set()

_apps_root = lambda: os.environ.get(  # noqa: E731
    "APPS_DIR",
    os.path.join(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui"), "apps"),
)

#: The app's own preview URL, the same one app_smoke drives.
PREVIEW_BASE_URL = os.environ.get(
    "PREVIEW_BASE_URL", "http://localhost:8210/tasks/preview-app")


def _safe_slug(slug: str) -> str:
    """A slug that cannot leave the apps tree.

    Both entry points take this straight from a URL, so "../../etc" and "a/b"
    are refused here rather than resolved into a path and hoped about.
    """
    s = (slug or "").strip()
    if not _SLUG_RE.match(s):
        raise ValueError("Invalid slug")
    return s


def app_dir(slug: str) -> str:
    return os.path.join(_apps_root(), _safe_slug(slug))


def thumb_path(slug: str) -> str:
    return os.path.join(app_dir(slug), ".thumb", "preview.jpg")


def _newest_source_mtime(root: str) -> float:
    """Newest mtime among the app's own files, ignoring build noise."""
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            try:
                m = os.path.getmtime(os.path.join(dirpath, name))
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


def is_stale(slug: str) -> bool:
    """Whether this app needs a new picture.

    False for an app that does not exist: nothing to photograph, and returning
    True would queue a capture for every 404.
    """
    try:
        root = app_dir(slug)
    except ValueError:
        return False
    if not os.path.isdir(root):
        return False
    png = thumb_path(slug)
    try:
        made = os.path.getmtime(png)
    except OSError:
        return True
    return _newest_source_mtime(root) > made


def is_capturing(slug: str) -> bool:
    return slug in _in_flight


async def _capture(slug: str) -> bool:
    """Screenshot the app's own preview page. Seam: tests replace this."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("app_thumb: playwright unavailable, no thumbnail for %s", slug)
        return False

    out = Path(thumb_path(slug))
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{PREVIEW_BASE_URL}/{slug}/"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(viewport=VIEWPORT,
                                                device_scale_factor=DEVICE_SCALE)
            page = await context.new_page()
            await page.goto(url, wait_until="load",
                            timeout=CAPTURE_TIMEOUT_MS)
            await page.wait_for_timeout(SETTLE_MS)
            # Above the fold only. A full-page shot of a long landing page
            # renders as an unreadable sliver in a card.
            await page.screenshot(path=str(out), full_page=False,
                                  type="jpeg", quality=JPEG_QUALITY)
        finally:
            await browser.close()
    return out.is_file()


async def ensure_thumb(slug: str) -> bool:
    """Capture this app's picture if it needs one. Never raises.

    A capture failure is not a page failure: the card simply shows nothing, and
    the next visit tries again.
    """
    try:
        slug = _safe_slug(slug)
    except ValueError:
        return False
    if not is_stale(slug):
        return False
    if slug in _in_flight:
        return False
    _in_flight.add(slug)
    try:
        async with _lock:
            ok = await _capture(slug)
        if ok:
            logger.info("app_thumb: captured %s", slug)
        return bool(ok)
    except Exception as e:  # noqa: BLE001 - a thumbnail is never worth an error
        logger.warning("app_thumb: capture failed for %s (%s)", slug,
                       type(e).__name__)
        return False
    finally:
        # Always cleared. Leaving a crashed slug marked in-flight would mean it
        # could never get a picture again without a restart.
        _in_flight.discard(slug)
