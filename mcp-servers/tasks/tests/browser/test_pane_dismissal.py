"""Closing the App Builder pane must take a deliberate action.

Reported 2026-08-20 with a screenshot: the user was in App Builder with a live
preview running, clicked the sidebar collapse control, and was dropped on a
blank chat with the pane gone and the address bar back at the root.

The cause was a blanket handler — ANY click outside the pane closed it:

    document.addEventListener("click", (e) => {
      if (!isOpen()) return;
      if (wrap.contains(t)) return;
      if (t.closest(NAV_EMBED_SELECTOR)) return;
      closeAiuiEmbed();
    }, true);

The pane is a full work surface — a running preview, an unsent prompt in the
build box — not a dropdown, and it should not be dismissed by a stray click on
the surrounding chrome. Reproduced in a browser before the fix: clicking a
plain button closed it.

The rule is now: a LINK navigates, so following one legitimately leaves the
pane; a BUTTON is chrome, so it must not. The X and Escape are unchanged and
remain the deliberate ways out.
"""
import pathlib
import shutil

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"


@pytest.fixture()
def page(tmp_path_factory):
    work = tmp_path_factory.mktemp("dismiss")
    shutil.copy(STATIC / "task-panel.js", work / "task-panel.js")
    shutil.copy(HERE / "shell_with_chrome.html", work / "shell.html")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page()
        pg.goto((work / "shell.html").as_uri())
        pg.wait_for_selector("[data-aiui-cron-jobs]", timeout=8000)
        pg.locator("[data-aiui-cron-jobs]").click()
        pg.wait_for_selector(OPEN_PANE, timeout=5000)
        yield pg
        browser.close()


def test_clicking_chrome_does_not_dismiss_the_pane(page):
    """The exact reported action: collapse the sidebar while working."""
    page.locator("#sidebar-toggle").click()
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 1, (
        "a plain chrome button closed the pane — a running preview and an "
        "unsent prompt are lost to a stray click")


def test_clicking_a_link_still_dismisses_it(page):
    """Following a link genuinely leaves; the pane must not cover the
    destination."""
    page.locator("#a-chat").click()
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 0, (
        "clicking a navigating link left the pane covering the page it "
        "navigated to")


def test_escape_still_closes(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert page.locator(OPEN_PANE).count() == 0, "Escape stopped closing the pane"


def test_clicking_inside_the_pane_never_closes_it(page):
    page.locator("[data-aiui-embed]").click(position={"x": 5, "y": 5})
    page.wait_for_timeout(300)
    assert page.locator(OPEN_PANE).count() == 1
