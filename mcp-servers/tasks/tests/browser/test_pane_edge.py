"""The pane starts where Open WebUI's sidebar really ends, and follows it.

Measured on the live site on 2026-10-05 (Open WebUI v0.11.4, 1920x1080, the
sidebar collapsed): the rail, <div id="sidebar">, is 42px wide and the pane
opened at x=260. aiuiSidebarRightEdge() accepted only a column 120 to 520px
wide, found none, and fell back to 260, which left an empty strip about 218px
wide between the rail and the page.

Collapsing is not a resize. Recorded frame by frame on the live site: opening
the sidebar REMOVES the rail and moves id="sidebar" onto a fixed 245px panel
that slides in over about 200ms; closing inserts a NEW rail, and the panel
narrows to 0 without the id, keeping our entries inside it.

sidebar_collapsed_rail.html is that DOM trimmed to structure, with the live
geometry written in as inline styles and the swap reproduced by its toggle.
The first test checks the fixture still has the measured shape, because every
other test here means nothing without it.
"""
import pathlib
import shutil

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
PANE = "[data-aiui-embed]"
OPEN_PANE = "[data-aiui-embed][data-open]"

#: openAiuiEmbed re-measures every 250ms for 3s after an open. A person
#: collapses the sidebar long after that, so the toggle tests wait it out;
#: otherwise they would pass on that poll alone and prove nothing.
AFTER_OPEN_POLL_MS = 3500
#: The live panel slides for about 200ms.
SLIDE_MS = 600


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, tmp_path):
    """The REAL task-panel.js beside the fixture, at the measured window."""
    shutil.copy(STATIC / "task-panel.js", tmp_path / "task-panel.js")
    shutil.copy(HERE / "sidebar_collapsed_rail.html", tmp_path / "index.html")
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto((tmp_path / "index.html").as_uri())
    pg.wait_for_selector("#sidebar [data-aiui-agents]", timeout=8000)
    yield pg
    pg.close()


def _open_agents(page):
    page.locator("#sidebar [data-aiui-agents]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)


def _pane_left(page):
    return page.locator(PANE).bounding_box()["x"]


def _sidebar_right(page):
    box = page.locator("#sidebar").bounding_box()
    return box["x"] + box["width"]


def test_the_fixture_has_the_shape_measured_live(page):
    rail = page.locator("#sidebar").bounding_box()
    assert (rail["x"], rail["width"], rail["height"]) == (0, 42, 1080)
    seed = page.locator("[data-aiui-graph]").bounding_box()
    assert (seed["x"], seed["y"], seed["width"], seed["height"]) == (4, 298, 33, 32)


def test_the_pane_starts_at_the_collapsed_rail(page):
    _open_agents(page)
    assert _pane_left(page) == 42, (
        f"the pane starts at {_pane_left(page)} but the rail ends at 42, "
        "leaving an empty strip between them")


def test_the_pane_never_covers_the_rail(page):
    _open_agents(page)
    entry = page.locator("#sidebar [data-aiui-agents]").bounding_box()
    assert _pane_left(page) >= entry["x"] + entry["width"]


def test_the_pane_follows_the_sidebar_when_it_opens(page):
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.locator('#sidebar button[aria-label="Open Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    assert page.locator(OPEN_PANE).count() == 1, "opening the sidebar closed the pane"
    assert _sidebar_right(page) == 245
    assert _pane_left(page) == 245, (
        f"the sidebar opened to 245px and the pane stayed at {_pane_left(page)}")


def test_the_pane_follows_the_sidebar_when_it_closes_again(page):
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.locator('#sidebar button[aria-label="Open Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    page.locator('#sidebar button[aria-label="Close Sidebar"]').click()
    page.wait_for_timeout(SLIDE_MS)
    assert _sidebar_right(page) == 42
    assert _pane_left(page) == 42, (
        f"the sidebar closed to the 42px rail and the pane stayed at "
        f"{_pane_left(page)}")


def test_the_pane_follows_a_sidebar_still_sliding_when_the_page_changes(page):
    """Recorded live: our entries were put back into the panel when it was
    already 124px into its 245px slide, so the re-measure that a DOM change
    triggers can land mid-slide. The pane must still end where the panel
    does, not where it happened to be at that moment."""
    _open_agents(page)
    page.wait_for_timeout(AFTER_OPEN_POLL_MS)
    page.evaluate("""() => new Promise((done) => {
      document.querySelector('#sidebar button[aria-label="Open Sidebar"]').click();
      setTimeout(() => {
        document.body.appendChild(document.createElement("i"));
        done();
      }, 60);
    })""")
    page.wait_for_timeout(SLIDE_MS)
    assert _pane_left(page) == 245, (
        f"the panel finished at 245px and the pane stopped at {_pane_left(page)}")
