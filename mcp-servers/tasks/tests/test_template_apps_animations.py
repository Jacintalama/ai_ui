"""Positive-path animation test — verifies count-up actually fires.

This complements the reduced-motion test in test_template_apps_static.py
(which verifies animations are SKIPPED under reduced-motion). Without
this, count-up bugs that prevent the animation from completing would
go undetected.

NOTE: The agency template loads src/main.js via <script type="module">,
which requires an HTTP server (browsers block ES-module cross-origin
requests from file:// null origin). We spin up a tiny stdlib server
in a background thread for the duration of the test.
"""
import pytest

playwright = pytest.importorskip("playwright.sync_api")


def test_agency_stats_count_up_completes(tmp_path):
    """Load agency/index.html over a local HTTP server, scroll the stats
    strip into view, wait 2 s, confirm the rendered numbers equal their
    target values."""
    import http.server
    import threading
    import socketserver
    from playwright.sync_api import sync_playwright
    from pathlib import Path

    agency_dir = Path(__file__).resolve().parents[1] / "template_apps" / "agency"

    # Spin up a simple HTTP server rooted at the agency directory.
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None  # silence access log in test output

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(agency_dir), **kwargs)

        def log_message(self, *args):  # noqa: D102
            pass  # silence access log

    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()

        url = f"http://127.0.0.1:{port}/index.html"
        expected = {"12": True, "247": True, "89": True, "34": True}

        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle")
            # Scroll stats into view, wait for count-up to settle.
            page.evaluate(
                "document.querySelector('[data-section=\"stats\"]').scrollIntoView()"
            )
            page.wait_for_timeout(2200)
            # Read the rendered stat numbers.
            rendered = page.evaluate("""
              Array.from(document.querySelectorAll('[data-section="stats"] [x-text="n"]'))
                .map(el => el.textContent.trim())
            """)
            browser.close()

        httpd.shutdown()

    for v in expected:
        assert v in rendered, f"expected count-up to render {v}, got {rendered}"
