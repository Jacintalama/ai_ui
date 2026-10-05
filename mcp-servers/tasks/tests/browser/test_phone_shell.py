"""On a phone, /ai-agents opens, and never over the sign-in page.

Measured on the live site on 2026-10-05 at 390x844, signed in: the page at
/ai-agents was still the plain chat home after 60 s. The shell opens a pane
only once "the app is up", and it judged that by sidebar links. A phone has
none: Open WebUI drops the rail under 768px and shows one 47px top bar.

The other half is the guard that check exists for. A signed-out visitor is
sent to /auth, and a pane opened there would cover the sign-in form and spend
the request. So the new signal had to be present on the signed-in phone home
and absent on /auth. main#main-content is: checked live at 390x844 and
1920x1080, including while a signed-out "/" and a dead token were being
redirected to /auth, where it never appeared even for a moment.

shell_phone.html holds both pages, trimmed from those captures, behind a small
router. These run over HTTP because the rescue and pushState need a real
origin; file:// swallows both.
"""
import functools
import http.server
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"
OPEN_PANE = "[data-aiui-embed][data-open]"
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1920, "height": 1080}

#: What a pane's iframe loads. Only its presence matters here.
STUB = b"<!doctype html><meta charset='utf-8'><title>stub pane</title>"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body, ctype = (STATIC / "task-panel.js").read_bytes(), "application/javascript"
        elif path.startswith("/tasks/"):
            body, ctype = STUB, "text/html"
        else:
            # 200 with the shell for every other path, like the real server.
            body, ctype = (HERE / "shell_phone.html").read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def base_url():
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(HERE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


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
def phone(browser):
    pg = browser.new_page(viewport=PHONE)
    yield pg
    pg.close()


def test_the_fixture_has_no_sidebar_links_like_the_live_phone(phone, base_url):
    """Guards the rest: this is the condition that kept the pane shut."""
    phone.goto(base_url + "/")
    phone.wait_for_selector("main#main-content", state="attached")
    for sel in ('a[href="/"]', 'a[href="/notes"]', 'a[href="/calendar"]',
                'a[href="/workspace"]', "#sidebar"):
        assert phone.locator(sel).count() == 0, sel
    bar = phone.locator("nav").bounding_box()
    assert (bar["x"], bar["y"], bar["width"], bar["height"]) == (0, 0, 390, 47)


def test_a_phone_opens_the_agents_pane(phone, base_url):
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    assert "/tasks/agents" in phone.get_attribute(f"{OPEN_PANE} iframe", "src")
    assert phone.evaluate("location.pathname") == "/ai-agents"


def test_the_phone_pane_is_full_width_under_the_top_bar(phone, base_url):
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    box = phone.locator(OPEN_PANE).bounding_box()
    assert (box["x"], box["y"], box["width"], box["height"]) == (0, 47, 390, 797)


def test_the_hamburger_stays_reachable_over_the_pane(phone, base_url):
    """A phone has no Escape key, and every link that would close the pane is
    under it. The hamburger is the way out, so the pane must not cover it."""
    phone.goto(base_url + "/ai-agents")
    phone.wait_for_selector(OPEN_PANE, timeout=8000)
    hit = phone.evaluate("""() => {
      const r = document.getElementById("sidebar-toggle-button").getBoundingClientRect();
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!(el && el.closest("#sidebar-toggle-button"));
    }""")
    assert hit, "the pane covers the hamburger, so a phone cannot leave it"


@pytest.mark.parametrize("viewport", [PHONE, DESK], ids=["phone", "desktop"])
def test_a_pane_never_opens_over_the_sign_in_page(browser, base_url, viewport):
    """The request waits, unspent, for the sign-in to finish."""
    pg = browser.new_page(viewport=viewport)
    try:
        pg.goto(base_url + "/auth")
        pg.evaluate(
            "() => sessionStorage.setItem('__aiuiOpenPath',"
            " JSON.stringify({path: '/ai-agents', at: Date.now()}))")
        pg.reload()
        pg.wait_for_selector("#auth-page", state="attached")
        pg.wait_for_timeout(1500)
        assert pg.locator(OPEN_PANE).count() == 0, "a pane opened over the sign-in form"
        assert pg.evaluate("() => sessionStorage.getItem('__aiuiOpenPath')"), \
            "the request was spent on the sign-in page"
    finally:
        pg.close()
