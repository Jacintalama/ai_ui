"""Arriving at a pane URL directly must land you in the app, not on a 404.

Ralph pasted https://.../cronjobs into the address bar and got Open WebUI's
bare "404: Not Found". The server was never the problem — it answers 200 with
the app shell — but Open WebUI's client-side router has no route for /cronjobs,
so after hydration it throws the app away and renders SvelteKit's error page:
no sidebar, no chat, no way out. Reproduced live against prod on all four:
/cronjobs, /app-builder, /video-generation AND /channel, which means Channels
shipped with this hole and nobody noticed, because clicking the sidebar has
always worked and only a pasted link or a reload hits it.

The fix bounces once through "/", where the router is happy, then reopens the
pane and puts the feature URL back. That is a real navigation, so it cannot be
tested against file:// — these tests run a throwaway HTTP server that imitates
the two behaviours that matter: any path returns the same shell, and the shell
"routes" to a 404 body for paths it does not know.

That bounce is now the fallback. It signed people out: the navigation aborts
Open WebUI's in-flight session check and Open WebUI deletes the token. The
primary rescue is an inline <head> script in openwebui-overrides/index.html
that moves the URL to "/" before the app starts, with no navigation at all.
The last test here runs that script, lifted verbatim from the real override,
in front of the same shell.
"""
import functools
import http.server
import pathlib
import re
import shutil
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

HERE = pathlib.Path(__file__).parent
STATIC = HERE.parents[1] / "static"

# Stands in for the Open WebUI shell: it knows "/" and nothing else, exactly
# like the real SvelteKit router.
SHELL = """<!doctype html><html><head><meta charset="utf-8"><title>Open WebUI</title>
<style>body{margin:0} #sidebar{position:fixed;left:0;top:0;width:260px;
  height:100vh;box-sizing:border-box;padding:8px}</style></head><body>
<div id="app"></div>
<script>
  // The router: only "/" renders the app. /auth renders the sign-in form, with
  // no sidebar, exactly like the real one. Anything else is a 404 with no
  // sidebar, which is the whole bug.
  if (location.pathname === "/auth") {
    document.getElementById("app").innerHTML =
      '<form><input type="email"><button>Sign in</button></form>';
  } else if (location.pathname === "/") {
    document.getElementById("app").innerHTML =
      '<nav id="sidebar">' +
      '<div class="row"><a href="/" draggable="false"><span>New Chat</span></a></div>' +
      '<div class="row"><a href="/notes" draggable="false"><span>Notes</span></a></div>' +
      '</nav>';
  } else {
    document.getElementById("app").textContent = "404: Not Found";
  }
</script>
<script src="/task-panel.js"></script>
</body></html>"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    shell = SHELL

    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/task-panel.js":
            body = (pathlib.Path(self.directory) / "task-panel.js").read_bytes()
            ctype = "application/javascript"
        else:
            body = self.shell.encode()
            ctype = "text/html"
        self.send_response(200)          # 200 for EVERY path, like the real one
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep pytest output clean
        pass


def _serve(tmp_path_factory, shell):
    d = tmp_path_factory.mktemp("shell")
    shutil.copy(STATIC / "task-panel.js", d / "task-panel.js")
    handler = functools.partial(
        type("_ShellHandler", (_Handler,), {"shell": shell}), directory=str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    srv = _serve(tmp_path_factory, SHELL)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _override_head_rescue() -> str:
    """The inline rescue <script> from the real override's <head>, verbatim.

    Lifted from the file rather than retyped, so this cannot pass against a
    script the test author imagined. Skips only where the override is not
    part of the checkout (the tasks image ships tests/ without it)."""
    parents = HERE.parents
    override = (parents[3] / "openwebui-overrides" / "index.html"
                if len(parents) > 3 else None)
    if override is None or not override.exists():
        pytest.skip("openwebui-overrides/index.html is not in this checkout")
    head = override.read_text(encoding="utf-8").split("</head>", 1)[0]
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", head, re.S):
        if "sessionStorage" in m.group(0):
            return m.group(0)
    return ""


@pytest.fixture(scope="module")
def override_base_url(tmp_path_factory):
    rescue = _override_head_rescue()
    assert rescue, "openwebui-overrides/index.html has no <head> rescue script"
    # Same place as in the real file: in <head>, ahead of the app's scripts.
    srv = _serve(tmp_path_factory, SHELL.replace("</title>", "</title>\n" + rescue, 1))
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


PANE_URLS = ["/cronjobs", "/app-builder", "/video-generation", "/channel",
             "/ai-agents"]


@pytest.mark.parametrize("url_path", PANE_URLS)
def test_a_pasted_pane_url_opens_the_feature(browser, base_url, url_path):
    pg = browser.new_page()
    try:
        pg.goto(base_url + url_path)
        pg.wait_for_selector("[data-aiui-embed][data-open]", timeout=8000)

        # The app is really there, not a 404 with a pane floating over it.
        assert "404" not in pg.inner_text("#app")
        assert pg.locator("#sidebar").count() == 1, "landed without a sidebar"
        # And the address bar still says what the user typed, so the URL is
        # worth pasting to someone else.
        assert pg.url == base_url + url_path
    finally:
        pg.close()


def test_the_404_is_not_left_in_the_back_button(browser, base_url):
    """The bounce uses replace(), so going back must reach whatever came
    before, never the dead page we just escaped."""
    pg = browser.new_page()
    try:
        pg.goto(base_url + "/")
        pg.wait_for_selector("#sidebar", timeout=8000)
        pg.goto(base_url + "/cronjobs")
        pg.wait_for_selector("[data-aiui-embed][data-open]", timeout=8000)
        pg.go_back()
        pg.wait_for_timeout(400)
        assert "404" not in pg.inner_text("#app")
    finally:
        pg.close()


def test_a_normal_page_is_left_alone(browser, base_url):
    """Only the four pane URLs bounce. Everything else must load untouched, or
    this would put an extra page load in front of the whole app."""
    pg = browser.new_page()
    try:
        pg.goto(base_url + "/")
        pg.wait_for_selector("#sidebar", timeout=8000)
        pg.wait_for_timeout(500)
        assert pg.url == base_url + "/"
        assert pg.locator("[data-aiui-embed][data-open]").count() == 0, \
            "a pane opened on a page nobody asked for one on"
    finally:
        pg.close()


def test_the_request_survives_a_detour_through_sign_in(browser, base_url):
    """Signed out, "/" bounces to /auth before the app ever renders. The
    pending open has to outlive that, or pasting a link while logged out
    silently drops you on the chat home instead of the feature."""
    pg = browser.new_page()
    try:
        pg.goto(base_url + "/cronjobs")
        pg.wait_for_selector("[data-aiui-embed][data-open]", timeout=8000)
        # Simulate the sign-in redirect chain landing back on "/" afterwards.
        pg.evaluate(
            "() => sessionStorage.setItem('__aiuiOpenPath',"
            " JSON.stringify({path: '/cronjobs', at: Date.now()}))")
        pg.goto(base_url + "/auth")
        pg.wait_for_timeout(400)
        pg.goto(base_url + "/")
        pg.wait_for_selector("[data-aiui-embed][data-open]", timeout=8000)
        assert pg.url == base_url + "/cronjobs"
    finally:
        pg.close()


def test_a_stale_request_does_not_ambush_a_later_visit(browser, base_url):
    """The key is only cleared when a pane actually opens, so it has to expire
    on its own — otherwise a pane springs open on some unrelated visit later
    in the same tab."""
    pg = browser.new_page()
    try:
        pg.goto(base_url + "/")
        pg.wait_for_selector("#sidebar", timeout=8000)
        pg.evaluate(
            "() => sessionStorage.setItem('__aiuiOpenPath',"
            " JSON.stringify({path: '/cronjobs', at: Date.now() - 60*60*1000}))")
        pg.goto(base_url + "/")
        pg.wait_for_selector("#sidebar", timeout=8000)
        pg.wait_for_timeout(600)
        assert pg.locator("[data-aiui-embed][data-open]").count() == 0
        assert pg.evaluate(
            "() => sessionStorage.getItem('__aiuiOpenPath')") is None
    finally:
        pg.close()


@pytest.mark.parametrize("url_path", PANE_URLS + ["/graph"])
def test_the_override_opens_a_pane_url_without_a_second_page_load(
        browser, override_base_url, url_path):
    """With the head script from the real override, the pane URL is loaded
    ONCE. A second document request would be the bounce, and the bounce is
    what aborted Open WebUI's session check and signed people out."""
    pg = browser.new_page()
    docs = []
    pg.on("request", lambda r: docs.append(r.url)
          if r.is_navigation_request() and r.frame == pg.main_frame else None)
    try:
        pg.goto(override_base_url + url_path)
        pg.wait_for_selector("[data-aiui-embed][data-open]", timeout=8000)
        assert "404" not in pg.inner_text("#app")
        assert pg.locator("#sidebar").count() == 1, "landed without a sidebar"
        assert pg.url == override_base_url + url_path
        assert docs == [override_base_url + url_path], (
            f"the page loaded {len(docs)} times: {docs}")
    finally:
        pg.close()
