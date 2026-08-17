"""What the Channels page actually measures, rendered.

Ralph asked for this page to be improved and sent a screenshot. Every problem
in it was invisible to the existing tests, which assert on copy: the numbers
below are the ones that were wrong, so they are the ones pinned here.

    a bot token field                1502px wide
    a collapsed row                  142px tall for three short lines
    of which pure empty space        ~29px, on every row, ten times over

The empty space was one `<p class="msg">` per row, rendered always and holding
a reserved line-height for a message that is only ever set after you press
something. Reserving it is right inside a form, where text appearing must not
shove the button out from under the cursor, and wrong on a collapsed row.

These are geometry assertions, so they need a browser. Served from a throwaway
HTTP server with the REAL catalogue JSON, so the shapes are the server's own.
"""
import functools
import http.server
import json
import os
import pathlib
import shutil
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")
os.environ.setdefault("GATEWAY_SLACK_ENABLED", "1")
os.environ.setdefault("GATEWAY_DISCORD_ENABLED", "1")
os.environ.setdefault("GATEWAY_TELEGRAM_BOT", "@aiuiteam_bot")

import routes_gateway as rg                              # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

#: The pane this page is rendered inside is routinely this wide, which is what
#: made a full-bleed layout a problem in the first place.
WIDE = 1600


def _payload() -> bytes:
    out = {"telegram_bot": "@aiuiteam_bot", "connections": []}
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        row["bot"] = None
        row.update(rg._route_for(row, "@aiuiteam_bot"))
        out["connections"].append(row)
    return json.dumps(out).encode()


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = tmp_path_factory.mktemp("channels")
    shutil.copy(STATIC / "gateway-link.html", work / "index.html")
    body = _payload()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                # noqa: N802
            if self.path.startswith("/tasks/gateway/connections"):
                data, ctype = body, "application/json"
            else:
                data, ctype = (work / "index.html").read_bytes(), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(work)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                         # noqa: BLE001
            srv.shutdown()
            pytest.skip(f"chromium not installed: {exc}")
        pg = browser.new_page(viewport={"width": WIDE, "height": 1000})
        pg.goto(base + "/")
        pg.wait_for_selector(".row", timeout=8000)
        yield pg
        browser.close()
    srv.shutdown()


def _row(page, label):
    return page.locator(f".row:has(.name:text-is('{label}'))")


def test_the_column_does_not_span_a_wide_pane(page):
    """Nothing here is a table; it is a settings list, and a settings list is
    read in a column. At 1600px the help text ran the full width."""
    width = page.evaluate("() => document.body.getBoundingClientRect().width")
    assert width <= 1100, f"body is {width}px wide inside a {WIDE}px pane"


def test_a_collapsed_row_is_not_padded_with_nothing(page):
    """142px for three short lines, ~29px of it a message paragraph holding
    space for text that is not there."""
    for label in ("Telegram", "Slack", "Discord"):
        h = _row(page, label).bounding_box()["height"]
        assert h <= 110, f"{label} row is {h}px tall"


def test_an_empty_message_line_takes_no_space(page):
    """The mechanism behind the row heights above, asserted directly so a
    future change to .msg cannot quietly put the padding back."""
    hidden = page.evaluate("""() => {
      const m = document.querySelector('.row > .msg');
      if (!m) return 'no .msg on any row';
      if (m.textContent.trim()) return 'not empty, cannot judge';
      return getComputedStyle(m).display; }""")
    assert hidden == "none", hidden


def test_a_credential_field_is_not_a_stripe_across_the_screen(page):
    """A token is read character by character. Stretched to a wide pane it
    becomes a rule with a few glyphs at one end."""
    _row(page, "Discord").click()
    page.wait_for_selector(".panel .botbox input", timeout=4000)
    w = page.locator(".panel .botbox input").first.bounding_box()["width"]
    assert w <= 600, f"the bot token field is {w}px wide"


def test_the_form_reads_as_a_stack_not_a_row(page):
    """Capping the input width let the Save button flow up beside the last
    field, because an input is inline-level. The button must stay below."""
    _row(page, "Discord").click()
    page.wait_for_selector(".panel .botbox input", timeout=4000)
    last_input = page.locator(".panel .botbox input").last.bounding_box()
    save = page.locator(".panel button.primary").first.bounding_box()
    assert save["y"] >= last_input["y"] + last_input["height"] - 2, \
        "Save sits beside the last field instead of under it"


def test_who_relays_your_messages_is_said_before_you_can_connect(page):
    """The caveat moved off the collapsed row, where it was a third line of
    near-identical boilerplate on every relayed channel. It must still be read
    on the way in, and opening the row IS the way in."""
    row = _row(page, "Discord")
    collapsed = row.locator(".naming").inner_text()
    assert "pass through" not in collapsed, \
        "the caveat is back on the collapsed row"
    row.click()
    page.wait_for_selector(".panel", timeout=4000)
    assert "pass through" in row.locator(".panel").inner_text()


def test_a_panel_never_opens_with_a_double_rule(page):
    """A heading that opens a panel sits directly under the panel's own
    divider, so its border drew a second line with a band of empty space
    between them. Telegram shows that shape: quick path first, no caveat."""
    row = _row(page, "Telegram")
    row.click()
    page.wait_for_selector(".panel", timeout=4000)
    style = row.locator(".panel > .botheadline").first.evaluate(
        "el => { const c = getComputedStyle(el);"
        " return c.borderTopWidth + '|' + c.marginTop; }")
    assert style.startswith("0px"), f"second divider under the panel rule: {style}"
