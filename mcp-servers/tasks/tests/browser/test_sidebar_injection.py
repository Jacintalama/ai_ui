"""Render task-panel.js in a real browser and check what a user would SEE.

Why this file exists. `task-panel.js` had no test of any kind, and the static
checks in `tests/test_nav_entries.py` — which only parse the source — passed
while the injector produced four sidebar entries that all read "Notes" and all
linked to /notes. The injector's own `console.log` said "sidebar entry
injected" for each one. Nothing short of rendering it caught that.

The cause: `buildEntry` CLONES an existing sidebar row and rewrites it. Which
row gets cloned depends on which anchor exists — Workspace for admins, Notes
for everyone else — so every assumption baked into the rewrite ("the label
says Workspace", "the href is ours") silently broke the moment a non-admin
cloned a different row.

Two fixtures, because the admin and non-admin paths clone DIFFERENT rows and
only one of them was ever exercised in production:
  sidebar_admin.html     — has /workspace, the pre-existing path
  sidebar_nonadmin.html  — no /workspace, which is what regular users get

Skipped automatically when Playwright or its browser is not installed, so it
never breaks a normal `pytest tests/` run:

    pip install playwright && playwright install chromium
    pytest tests/browser/ -v
"""
import pathlib
import shutil

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"

# (dedupe attribute, visible label, expected href)
# Every entry now opens an in-page pane rather than navigating, so none of them
# may carry an href — otherwise ctrl-click, middle-click and hover would all
# bypass the pane and boot a standalone page, which is the behaviour these were
# changed to get rid of.
ENTRIES = [
    ("data-aiui-build-website", "App Builder", None),
    ("data-aiui-video-gen", "Video Generation", None),
    ("data-aiui-cron-jobs", "Cron Jobs", None),
    ("data-aiui-channels", "Channels", None),
    ("data-aiui-graph", "Graph", None),
]


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    """A page with the REAL task-panel.js beside the fixtures.

    The script is copied rather than referenced across directories so the
    fixture's plain `<script src="./task-panel.js">` resolves — and so the
    test can only ever run against the shipped file.
    """
    work = tmp_path_factory.mktemp("sidebar")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    for html in ("sidebar_admin.html", "sidebar_nonadmin.html"):
        shutil.copy(HERE / html, work / html)

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary absent
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page()
        pg._aiui_work = work  # noqa: SLF001 - test-local handle
        yield pg
        browser.close()


def _load(page, fixture):
    page.goto((page._aiui_work / fixture).as_uri())  # noqa: SLF001
    # The injector runs off a MutationObserver + requestAnimationFrame.
    page.wait_for_selector("[data-aiui-graph]", timeout=8000)


@pytest.mark.parametrize("fixture", ["sidebar_nonadmin.html", "sidebar_admin.html"])
@pytest.mark.parametrize("attr,label,href", ENTRIES)
def test_the_entry_shows_its_own_label(page, fixture, attr, label, href):
    """The bug this file was written for: every entry read "Notes"."""
    _load(page, fixture)
    el = page.locator(f"[{attr}]")
    assert el.count() == 1, f"{label}: expected exactly one, got {el.count()}"
    assert el.first.inner_text().strip() == label


@pytest.mark.parametrize("fixture", ["sidebar_nonadmin.html", "sidebar_admin.html"])
@pytest.mark.parametrize("attr,label,href", ENTRIES)
def test_the_entry_points_at_its_own_target(page, fixture, attr, label, href):
    """Cloned rows kept the source row's href, so hover, middle-click and
    ctrl-click all went to the wrong page even though a plain click worked."""
    _load(page, fixture)
    anchors = page.locator(f"[{attr}] a")
    if anchors.count() == 0:
        pytest.skip(f"{label}: fixture row has no nested anchor")
    assert anchors.first.get_attribute("href") == href


def test_a_non_admin_gets_them_all_without_a_workspace_link(page):
    """The root cause. Open WebUI renders a[href="/workspace"] only for admins
    or users with >=1 workspace permission, and this deployment sets all five
    to false — so with a single anchor, non-admins saw nothing at all."""
    _load(page, "sidebar_nonadmin.html")
    assert page.locator('a[href="/workspace"]').count() == 0
    for attr, label, _ in ENTRIES:
        assert page.locator(f"[{attr}]").count() == 1, f"{label} missing"


def test_injection_is_idempotent(page):
    """The SPA re-renders constantly; the observer fires on every mutation."""
    _load(page, "sidebar_nonadmin.html")
    page.evaluate(
        "document.querySelector('#sidebar').appendChild("
        "document.createElement('div'))")
    page.wait_for_timeout(600)
    for attr, label, _ in ENTRIES:
        assert page.locator(f"[{attr}]").count() == 1, f"{label} duplicated"


# --- opening in the shell -----------------------------------------------
#
# The static parse in tests/test_feature_pages_embed.py can only prove the
# CONFIG says embed. These prove the click actually does it, which is the part
# that has broken before: the entries carried a stale href and a plain click
# looked fine while every other way of clicking navigated away.

PANE = "[data-aiui-embed]"
OPEN_PANE = "[data-aiui-embed][data-open]"


def test_clicking_a_feature_opens_a_pane_instead_of_leaving_the_page(page):
    _load(page, "sidebar_nonadmin.html")
    before = page.url
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    assert page.url == before, "the click navigated away instead of opening a pane"
    src = page.get_attribute(f"{OPEN_PANE} iframe", "src")
    assert "/tasks/static/cron.html" in src


@pytest.mark.parametrize("fixture", ["sidebar_nonadmin.html", "sidebar_admin.html"])
@pytest.mark.parametrize("attr,label,_href", ENTRIES)
def test_the_entry_looks_clickable(page, fixture, attr, label, _href):
    """Ralph: "WHEN MY CURSOR IS IN THE TOP NOT CHANGING TO HAND".

    The whole row is clickable, but the browser only gives a hand cursor to
    <a href>, and these entries have their href stripped so that ctrl-click
    cannot bypass the pane. That silently took the hand cursor with it, and
    nothing that parses the source can see it — the computed style is the only
    thing that knows.
    """
    _load(page, fixture)
    row = page.locator(f"[{attr}]")
    assert row.evaluate("el => getComputedStyle(el).cursor") == "pointer"
    inner = page.locator(f"[{attr}] a")
    if inner.count():
        assert inner.first.evaluate("el => getComputedStyle(el).cursor") == "pointer"


def test_the_pane_never_covers_the_sidebar(page):
    """The pane is position:fixed and starts at a MEASURED left edge. If that
    measurement misses, the pane lands on top of the nav entries and the user
    cannot switch features or start a chat — they are stuck on whatever they
    opened, with no way out but the close button."""
    _load(page, "sidebar_nonadmin.html")
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    entry = page.locator("[data-aiui-cron-jobs]").bounding_box()
    pane = page.locator(PANE).bounding_box()
    assert pane["x"] >= entry["x"] + entry["width"], (
        f"pane starts at {pane['x']} but the nav entry runs to "
        f"{entry['x'] + entry['width']}")


def test_reopening_a_feature_reuses_the_page_it_already_loaded(page):
    """The "no loading" requirement, checked the only way that means anything:
    the SAME iframe element must come back, not a fresh one. A rebuilt frame
    looks identical in a screenshot and costs a full page boot every time."""
    _load(page, "sidebar_nonadmin.html")
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    page.evaluate(
        "document.querySelector('[data-aiui-embed] iframe').__probe = 'first'")

    page.locator("[data-aiui-video-gen]").click()
    page.wait_for_timeout(300)
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_timeout(300)

    # Both pages are still in the DOM, and the one showing is the one clicked.
    assert page.locator(f"{PANE} iframe").count() == 2, "the pane rebuilt its frames"
    survived = page.evaluate(
        "Array.from(document.querySelectorAll('[data-aiui-embed] iframe'))"
        ".find(f => f.__probe === 'first') ? true : false")
    assert survived, "the cron page was thrown away and would reload on reopen"
    shown = page.evaluate(
        "Array.from(document.querySelectorAll('[data-aiui-embed] iframe'))"
        ".filter(f => f.style.display !== 'none').map(f => f.src)")
    assert len(shown) == 1 and "cron.html" in shown[0], shown


def test_switching_features_does_not_close_the_pane(page):
    """The outside-click handler runs in the capture phase, so it sees the
    click on the next nav entry BEFORE that entry's own handler. Naming only
    the Graph entry there meant every other switch closed the pane first."""
    _load(page, "sidebar_nonadmin.html")
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    page.locator("[data-aiui-build-website]").click()
    page.wait_for_timeout(300)
    assert page.locator(OPEN_PANE).count() == 1, "switching closed the pane"
    src = page.get_attribute(f"{OPEN_PANE} iframe:not([style*='display: none'])", "src")
    assert "/tasks/app-builder" in src


def test_closing_keeps_the_loaded_pages_for_next_time(page):
    _load(page, "sidebar_nonadmin.html")
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    page.locator(f"{PANE} button[aria-label='Close']").click()
    page.wait_for_timeout(200)
    assert page.locator(OPEN_PANE).count() == 0, "close did not hide the pane"
    assert page.locator(f"{PANE} iframe").count() == 1, \
        "close destroyed the loaded page, so reopening would load it again"


def test_clicking_a_normal_sidebar_link_still_closes_the_pane(page):
    """The pane must not become a trap: anything that is not one of ours
    returns the user to the app."""
    _load(page, "sidebar_nonadmin.html")
    page.locator("[data-aiui-cron-jobs]").click()
    page.wait_for_selector(OPEN_PANE, timeout=4000)
    page.evaluate("document.querySelector('#sidebar').click()")
    page.wait_for_timeout(200)
    assert page.locator(OPEN_PANE).count() == 0
