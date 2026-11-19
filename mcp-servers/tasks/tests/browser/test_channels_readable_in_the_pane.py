"""The Channels page is readable inside the pane, whatever the device's theme.

Seen live on 2026-11-19 (screenshot from the user, Lukas said the same at
stand-up): the Channels pane showed near-black text on a near-black
background. The pane draws every embedded page on `background:#0b0b0b`
(task-panel.js, openAiuiEmbed). Cron Jobs, AI Agents and the App Builder
paint their own dark ground and light text; Channels alone left its
background transparent, inherited its text colour and declared
`color-scheme: light dark`, so on a device in LIGHT mode its text was the
light scheme's black, drawn over the pane's black.

So the page is loaded here the way the pane loads it, in an iframe with the
pane's own background, under both schemes, and what is measured is what a
person sees: the pixels behind the heading and the heading's colour.
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
PANEL_JS = (STATIC / "task-panel.js").read_text(encoding="utf-8")

#: The pane's own frame style, copied from openAiuiEmbed. Asserted below so
#: this test cannot drift from what the pane really does.
PANE_FRAME_STYLE = "width:100%;height:100%;border:0;display:block;background:#0b0b0b;"

HOST = ("<!doctype html><html><body style='margin:0;height:100vh'>"
        "<iframe id='f' src='/index.html' style='" + PANE_FRAME_STYLE + "'>"
        "</iframe></body></html>")


def _payload() -> bytes:
    out = {"telegram_bot": "@aiuiteam_bot", "connections": []}
    for entry in rg.CHANNEL_CATALOGUE:
        row = rg._channel_status(entry, {})
        row["bot"] = None
        row.update(rg._route_for(row, "@aiuiteam_bot"))
        out["connections"].append(row)
    return json.dumps(out).encode()


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    work = tmp_path_factory.mktemp("channels_theme")
    shutil.copy(STATIC / "gateway-link.html", work / "index.html")
    body = _payload()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                # noqa: N802
            if self.path.startswith("/tasks/gateway/connections"):
                data, ctype = body, "application/json"
            elif self.path.startswith("/index.html"):
                data, ctype = (work / "index.html").read_bytes(), "text/html"
            else:
                data, ctype = HOST.encode(), "text/html"
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
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rgb(css):
    nums = css[css.index("(") + 1:css.index(")")].replace("/", ",").split(",")
    return tuple(int(float(n)) for n in nums[:3])


def test_the_pane_style_used_here_is_the_real_one():
    assert PANE_FRAME_STYLE in PANEL_JS


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_heading_and_a_row_can_be_read_in_the_pane(base, scheme):
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                         # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            pg = browser.new_page(viewport={"width": 1400, "height": 900},
                                  color_scheme=scheme)
            pg.goto(base + "/")
            frame = pg.frame_locator("#f")
            frame.locator(".row .name").first.wait_for(timeout=8000)
            for sel in ("h1", ".row .name"):
                el = frame.locator(sel).first
                fg = _rgb(el.evaluate("e => getComputedStyle(e).color"))
                # The ground is what is on screen beside the text: sample the
                # pixel just left of the heading's box, inside the page.
                box = el.bounding_box()
                shot = pg.screenshot(clip={"x": max(box["x"] - 6, 0),
                                           "y": box["y"] + box["height"] / 2,
                                           "width": 1, "height": 1})
                from PIL import Image
                import io
                bg = Image.open(io.BytesIO(shot)).convert("RGB").getpixel((0, 0))
                ratio = _contrast(fg, bg)
                assert ratio >= 4.5, (
                    f"{scheme}: {sel} is rgb{fg} on rgb{bg}, contrast "
                    f"{ratio:.2f}:1")
        finally:
            browser.close()
