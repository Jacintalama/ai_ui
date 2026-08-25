"""A page shown inside the Open WebUI pane must not still act standalone.

All three feature pages carry their own "Back to chat" link in the top right.
That was right while a click on the sidebar navigated the whole window to them.
Now the sidebar opens them in a pane, and the same link does two wrong things
at once:

  1. It loads the ENTIRE Open WebUI app into the pane — an app inside an app,
     with a second sidebar and a second chat, inside a 1200px box.
  2. It sits underneath the pane's own close button, which is pinned to the
     same corner. Ralph's screenshot showed the two overlapping.

Neither is visible to any test that reads the source, and neither is visible to
the page itself in isolation. The check has to render the page in an iframe and
in a normal window and compare.
"""
import pathlib
import shutil

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
PAGES = ["video.html", "cron.html", "projects.html", "agents.html"]

HOST = """<!doctype html><meta charset="utf-8"><title>pane</title>
<body style="margin:0"><iframe id="f" src="./{page}"
  style="width:100%;height:600px;border:0"></iframe></body>"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    """The real pages, beside a host page that frames them."""
    d = tmp_path_factory.mktemp("chrome")
    for page in PAGES:
        shutil.copy(STATIC / page, d / page)
        (d / f"host_{page}").write_text(HOST.format(page=page), encoding="utf-8")
    return d


def _back_display(page_obj):
    return page_obj.evaluate(
        "() => { const a = document.querySelector('a.back');"
        " return a ? getComputedStyle(a).display : 'MISSING'; }")


@pytest.mark.parametrize("page_name", PAGES)
def test_the_back_link_is_hidden_inside_the_pane(browser, work, page_name):
    pg = browser.new_page()
    try:
        pg.goto((work / f"host_{page_name}").as_uri())
        frame = pg.frame_locator("#f")
        # Wait for the page's own markup, not the network (the API calls cannot
        # resolve from file:// and are irrelevant here).
        frame.locator("a.back").wait_for(state="attached", timeout=8000)
        display = pg.frames[1].evaluate(
            "() => getComputedStyle(document.querySelector('a.back')).display")
        assert display == "none", (
            f"{page_name}: 'Back to chat' is still live inside the pane; "
            f"clicking it loads the whole app into the pane")
    finally:
        pg.close()


@pytest.mark.parametrize("page_name", PAGES)
def test_the_back_link_still_works_standalone(browser, work, page_name):
    """The old URLs are still real pages — /video-generator is posted into
    Discord by the scheduler — so hiding the link everywhere would strand
    anyone who arrives that way."""
    pg = browser.new_page()
    try:
        pg.goto((work / page_name).as_uri())
        pg.wait_for_selector("a.back", state="attached", timeout=8000)
        assert _back_display(pg) != "none", (
            f"{page_name}: the standalone page lost its way back to the app")
    finally:
        pg.close()


@pytest.mark.parametrize("page_name", PAGES)
def test_the_whole_top_bar_is_hidden_inside_the_pane(browser, work, page_name):
    """The pane already names the feature and carries the close button, so the
    page repeating its own title there cost height and said nothing twice."""
    pg = browser.new_page()
    try:
        pg.goto((work / f"host_{page_name}").as_uri())
        frame = pg.frame_locator("#f")
        frame.locator(".topbar").wait_for(state="attached", timeout=8000)
        display = pg.frames[1].evaluate(
            "() => getComputedStyle(document.querySelector('.topbar')).display")
        assert display == "none", (
            f"{page_name}: the page still draws its own title bar inside the pane")
    finally:
        pg.close()


@pytest.mark.parametrize("page_name", PAGES)
def test_the_top_bar_survives_standalone(browser, work, page_name):
    """Standalone these are real pages, and the scheduler posts
    /video-generator into Discord. Somebody arriving that way has no pane
    around them, so this bar is their only way back."""
    pg = browser.new_page()
    try:
        pg.goto((work / page_name).as_uri())
        pg.wait_for_selector(".topbar", state="attached", timeout=8000)
        display = pg.evaluate(
            "() => getComputedStyle(document.querySelector('.topbar')).display")
        assert display != "none", (
            f"{page_name}: the standalone page lost its title bar and its way back")
    finally:
        pg.close()
