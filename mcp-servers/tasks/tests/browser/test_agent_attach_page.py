"""Attach a file or a picture to a message to the agents (2026-10-28).

Lukas asked for it on the agents page and in the office's chat windows.
agent-chat.js gives every composer an Attach row above the message box;
the chosen files show as chips that can be taken off, a picture is shrunk
in the browser and previewed, and the files go with the message as
multipart. The server side (agent_attach, the send route) is tested in
tests/test_agent_attach.py.

The pages, stylesheet and script are the real ones (office.html,
agents.html, agent-chat.js), served the way test_agent_talk serves them.
"""
import json
import re
import struct
import urllib.parse
import zlib

import pytest

import test_agent_talk as talk
from test_agent_talk import browser  # noqa: F401  (the shared fixture)

render = talk.render


def _png(w, h):
    """A plain PNG, w by h, made without an imaging library."""
    row = b"\x00" + b"\x30\x80\xc0" * w
    raw = zlib.compress(row * h)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _jpeg_size(data):
    """(width, height) from a JPEG's frame header."""
    i = 2
    while i < len(data):
        marker, size = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xC3:
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + size
    return None


def _parts(body: bytes, ctype: str):
    """A multipart body as {field: [(filename, content type, bytes)]}."""
    boundary = re.search(r"boundary=([^;]+)", ctype).group(1).encode()
    out = {}
    for part in body.split(b"--" + boundary)[1:-1]:
        head, _, data = part.partition(b"\r\n\r\n")
        head = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', head).group(1)
        fn = re.search(r'filename="([^"]*)"', head)
        ct = re.search(r"Content-Type: (\S+)", head)
        out.setdefault(name, []).append((fn.group(1) if fn else None,
                                         ct.group(1) if ct else None, data[:-2]))
    return out


def _open(browser, page_file):  # noqa: F811
    srv = talk._serve((talk.STATIC / page_file).read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    pg.errors, pg.posts = [], []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))

    def route(r):
        url = r.request.url
        if "/chat/send" in url:
            ctype = r.request.headers.get("content-type", "")
            body = r.request.post_data_buffer or b""
            if ctype.startswith("multipart/"):
                parts = _parts(body, ctype)
                text = parts.get("message", [(None, None, b"")])[0][2].decode()
                files = [f for f in parts.get("files", []) if f[0]]
                thumbs = json.loads(parts.get("thumbs", [(None, None, b"{}")])[0][2] or b"{}")
            else:
                form = urllib.parse.parse_qs(body.decode())
                text, files, thumbs = (form.get("message") or [""])[0], [], {}
            pg.posts.append({"ctype": ctype, "message": text, "files": files, "thumbs": thumbs})
            shown = [{"name": f[0], "kind": "image" if (f[1] or "").startswith("image/") else "text",
                      **({"thumb": thumbs[f[0]]} if f[0] in thumbs else {})} for f in files]
            r.fulfill(status=200, content_type="text/html",
                      body=render.turn_open(text, "t9", attached=shown) + render.turn_close())
            return
        if "/agents/stream" in url:
            r.fulfill(status=204)
            return
        if "/chat/thread" in url:
            r.fulfill(status=200, content_type="text/html", body=talk.THREAD)
            return
        if "/models/list" in url:
            body = {"items": talk.AGENTS, "total": len(talk.AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/todo" in url:
            body = {"open": [], "done": []}
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d/%s" % (srv.server_address[1], page_file))
    pg.srv = srv
    return pg


@pytest.fixture
def office(browser):  # noqa: F811
    pg = _open(browser, "office.html")
    pg.wait_for_selector("#cw-team #agent-thread .am.agent", state="visible")
    pg.wait_for_timeout(300)
    yield pg
    pg.close()
    pg.srv.shutdown()


TEAM = "#cw-team .ap-composer"


def _choose(pg, files, where=TEAM):
    pg.locator(where + " input.ap-files").set_input_files(files)
    pg.wait_for_function("s => document.querySelectorAll(s + ' .ap-chip').length > 0",
                         arg=where)


def _send(pg, words, where=TEAM):
    before = len(pg.posts)
    pg.locator(where + " input[name=message]").fill(words)
    pg.locator(where + " button[type=submit]").click()
    for _ in range(40):
        if len(pg.posts) > before:
            break
        pg.wait_for_timeout(100)
    pg.wait_for_timeout(300)
    return pg.posts[-1]


def test_the_office_window_has_attach_above_the_message_box(office):
    form = office.locator(TEAM)
    attach = form.locator(".ap-attach")
    assert attach.inner_text() == "Attach"
    box = form.locator("input[name=message]").bounding_box()
    assert attach.bounding_box()["y"] + attach.bounding_box()["height"] <= box["y"] + 1
    assert form.locator(":scope > button").all_inner_texts() == ["Send", "Talk"]
    # The message row stays one row: the box, Send and Talk side by side.
    rows = {round(b.bounding_box()["y"] + b.bounding_box()["height"] / 2) for b in
            [form.locator("input[name=message]")] + form.locator(":scope > button").all()}
    assert max(rows) - min(rows) <= 4, rows
    assert office.errors == [], office.errors


def test_a_private_window_gets_attach_too(office):
    office.evaluate("() => import('/tasks/static/office/js/dock.js').then(d => d.openChat('agent-mia-77'))")
    win = office.locator('#chatdock .cw[data-chat="agent-mia-77"]')
    win.wait_for(state="visible")
    office.wait_for_timeout(200)
    assert win.locator(".ap-composer .ap-attach").count() == 1


def test_the_agents_page_composer_has_attach(browser):  # noqa: F811
    pg = _open(browser, "agents.html")
    try:
        pg.wait_for_selector(".ap-composer .ap-attach", state="visible")
        assert pg.locator(".ap-composer .ap-attach").count() == 1
        assert pg.errors == [], pg.errors
    finally:
        pg.close()
        pg.srv.shutdown()


def test_a_chosen_file_is_a_chip_that_can_be_taken_off(office):
    _choose(office, [{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"Budget 4000"},
                     {"name": "plan.md", "mimeType": "text/markdown", "buffer": b"# Plan"}])
    chips = office.locator(TEAM + " .ap-chip .ap-chip-name")
    assert chips.all_inner_texts() == ["notes.txt", "plan.md"]
    office.locator(TEAM + " .ap-chip-x").first.click()
    assert chips.all_inner_texts() == ["plan.md"]
    names = office.evaluate("s => [...document.querySelector(s + ' input.ap-files').files].map(f => f.name)",
                            TEAM)
    assert names == ["plan.md"], "the input still carries the file taken off"


def test_a_file_goes_with_the_message_and_shows_in_the_bubble(office):
    _choose(office, [{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"Budget 4000"}])
    sent = _send(office, "what is the budget?")
    assert sent["ctype"].startswith("multipart/form-data")
    assert sent["message"] == "what is the budget?"
    assert [(f[0], f[2]) for f in sent["files"]] == [("notes.txt", b"Budget 4000")]
    bubble = office.locator("#agent-thread .am.user").last
    assert "notes.txt" in bubble.locator(".afile").inner_text()
    # Sent, so the chips are gone and the next message carries nothing.
    assert office.locator(TEAM + " .ap-chip").count() == 0
    again = _send(office, "and plain words")
    assert not again["ctype"].startswith("multipart/"), again["ctype"]


def test_a_picture_is_shrunk_and_previewed(office):
    _choose(office, [{"name": "board.png", "mimeType": "image/png", "buffer": _png(2400, 1200)}])
    assert office.locator(TEAM + " .ap-chip img").count() == 1
    sent = _send(office, "what does the board say")
    (name, ctype, data), = sent["files"]
    assert name == "board.jpg" and ctype == "image/jpeg", (name, ctype)
    assert _jpeg_size(data) == (1600, 800)
    assert sent["thumbs"]["board.jpg"].startswith("data:image/jpeg;base64,")
    img = office.locator("#agent-thread .am.user").last.locator(".afile.pic img")
    assert img.count() == 1


def test_more_than_three_files_are_refused_in_words(office):
    _choose(office, [{"name": "%d.txt" % i, "mimeType": "text/plain", "buffer": b"x"}
                     for i in range(4)])
    assert office.locator(TEAM + " .ap-chip").count() == 3
    assert "At most 3 files" in office.locator("#agent-thread .am.note").last.inner_text()
