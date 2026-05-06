"""Picker.js behavior tests using Playwright. The harness is loaded inside
an iframe (not as the top frame) so the picker's `window.parent !== window`
guard reflects production. The outer page records postMessages from the
iframe.
"""
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from contextlib import contextmanager

import pytest
from playwright.sync_api import sync_playwright

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
STATIC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_a, **_kw):
        pass

    def translate_path(self, path):
        # Strip query params and hash before mapping to disk.
        for sep in ("?", "#"):
            i = path.find(sep)
            if i != -1:
                path = path[:i]
        if path == "/picker.js":
            return os.path.join(STATIC, "picker.js")
        if path == "/" or path.endswith("/picker_harness.html"):
            return os.path.join(FIXTURES, "picker_harness.html")
        # Fallback to fixtures dir for any other path — but reject any path
        # that would escape FIXTURES via ../ traversal. The test harness only
        # listens on 127.0.0.1 with an ephemeral port, but defense-in-depth
        # avoids future copies of this handler accepting untrusted input.
        candidate = os.path.realpath(os.path.join(FIXTURES, path.lstrip("/")))
        fixtures_real = os.path.realpath(FIXTURES)
        if os.path.commonpath([candidate, fixtures_real]) != fixtures_real:
            return os.path.join(FIXTURES, "__forbidden__")  # 404
        return candidate


@contextmanager
def _server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()


@pytest.fixture
def harness_url():
    with _server() as port:
        yield f"http://127.0.0.1:{port}/picker_harness.html"


@pytest.fixture
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _outer_html(harness_url: str) -> str:
    """Build the outer test page that embeds the harness in an iframe."""
    return f"""
<!doctype html>
<html>
<head><title>Outer</title></head>
<body>
  <iframe id="iframe" src="{harness_url}" style="width:600px;height:400px;border:0"></iframe>
  <script>
    window.__msgs = [];
    window.addEventListener("message", (e) => window.__msgs.push(e.data));
  </script>
</body>
</html>
"""


def test_picker_posts_ready_on_load(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )
    msgs = page.evaluate("window.__msgs")
    assert any(m.get("type") == "io.picker.ready" for m in msgs)


def test_picker_activate_mounts_overlay(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    # Send activate INTO the iframe (not to the top frame).
    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)

    # The overlay element lives inside the iframe.
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    # Hover over the card border (top-left, just inside) so the topmost
    # element is the article itself, not a text child like h3.
    iframe_locator.locator("#card-1").hover(position={"x": 2, "y": 2})

    # The outer page (about:blank from set_content) is cross-origin to the
    # http-served iframe, so we can't read contentDocument directly. Use
    # Playwright's bounding_box() on the iframe locator instead — it works
    # cross-origin via the devtools protocol.
    overlay_box = iframe_locator.locator("#__io_picker_overlay").bounding_box()
    card_box = iframe_locator.locator("#card-1").bounding_box()
    assert overlay_box is not None
    assert card_box is not None
    # Overlay should be sized to the hovered card.
    assert overlay_box["width"] > 50 and overlay_box["height"] > 20
    assert abs(overlay_box["width"] - card_box["width"]) < 2
    assert abs(overlay_box["height"] - card_box["height"]) < 2


def test_picker_deactivate_removes_overlay(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.deactivate"}, "*"
      )
    """)
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="detached", timeout=2000)


def test_picker_click_posts_selected_payload(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    iframe_locator.locator("button.cta").click()
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.selected')",
        timeout=2000,
    )

    msg = page.evaluate("""
      () => window.__msgs.find(m => m && m.type === 'io.picker.selected')
    """)
    assert msg["tag"] == "BUTTON"
    assert "cta" in msg["selector"]
    assert msg["outerHtml"].startswith("<button")
    assert "color" in msg["styles"]
    assert msg["rect"]["w"] > 0
    assert msg["url"].endswith("/picker_harness.html")


def test_picker_click_outerhtml_truncated(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    iframe_locator = page.frame_locator("#iframe")
    # Stuff the card with a long string so outerHTML goes way past 2KB.
    # Run inside the iframe document.
    iframe_locator.locator("#card-1").evaluate("""
      (c) => c.appendChild(document.createTextNode('x'.repeat(10000)))
    """)
    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)
    iframe_locator.locator("#card-1").click(position={"x": 2, "y": 2})
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.selected')",
        timeout=2000,
    )
    msg = page.evaluate("""
      () => window.__msgs.find(m => m && m.type === 'io.picker.selected')
    """)
    assert len(msg["outerHtml"]) <= 2200


def test_picker_click_suppresses_form_submit(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    iframe_locator = page.frame_locator("#iframe")
    # Wire a submit detector INSIDE the iframe AND wrap the cta button in a form.
    # The picker's capture-phase suppression runs inside the iframe document.
    iframe_locator.locator("body").evaluate("""
      (body) => {
        const btn = body.querySelector('button.cta');
        const form = document.createElement('form');
        form.action = 'javascript:void(0)';
        btn.parentNode.insertBefore(form, btn);
        form.appendChild(btn);
        btn.type = 'submit';
        window.__submitted = false;
        window.addEventListener('submit', () => { window.__submitted = true; }, true);
      }
    """)

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)
    iframe_locator.locator("button.cta").click()

    # Read the iframe's window flag (NOT the outer page's).
    submitted = iframe_locator.locator("body").evaluate("(_b) => window.__submitted")
    assert submitted is False, "form submit should be suppressed by picker capture"


def test_picker_click_without_alt_picks_leaf_regression(browser, harness_url):
    """Guard against the Alt-walk in pickableTarget regressing the
    leaf-pick behavior covered by test_picker_click_posts_selected_payload."""
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    # Click the H3 directly with NO Alt held — must still pick the H3,
    # not its parent ARTICLE.
    iframe_locator.locator("#card-1 h3").click()
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.selected')",
        timeout=2000,
    )
    msg = page.evaluate(
        "() => window.__msgs.find(m => m && m.type === 'io.picker.selected')"
    )
    assert msg["tag"] == "H3"


def test_picker_escape_cancels(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    # Send Escape into the iframe — locator.press dispatches to the located
    # element, which puts the keyboard event in the iframe's document.
    iframe_locator.locator("body").press("Escape")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="detached", timeout=2000)

    msgs = page.evaluate("window.__msgs")
    assert any(m.get("type") == "io.picker.cancelled" for m in msgs)


def test_picker_alt_hover_picks_parent(browser, harness_url):
    page = browser.new_context().new_page()
    page.set_content(_outer_html(harness_url))
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.ready')",
        timeout=3000,
    )

    page.evaluate("""
      () => document.getElementById("iframe").contentWindow.postMessage(
        {type: "io.picker.activate"}, "*"
      )
    """)
    iframe_locator = page.frame_locator("#iframe")
    iframe_locator.locator("#__io_picker_overlay").wait_for(state="attached", timeout=2000)

    # Click the inner h3 with Alt held — picker should walk up one level
    # so the payload's tag is ARTICLE (the .card parent), not H3.
    iframe_locator.locator("#card-1 h3").click(modifiers=["Alt"])
    page.wait_for_function(
        "window.__msgs.some(m => m && m.type === 'io.picker.selected')",
        timeout=2000,
    )

    msg = page.evaluate(
        "() => window.__msgs.find(m => m && m.type === 'io.picker.selected')"
    )
    assert msg["tag"] == "ARTICLE"
