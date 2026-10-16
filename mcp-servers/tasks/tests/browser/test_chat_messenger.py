"""The conversation drawn the way a messenger draws it.

"can you fix the animation and chat of users.. you know like a facebook
messanger" (2026-10-16). What that means on screen, and what these pin:
what you said is a filled bubble on the right; what an agent said is a
bubble on the left with its avatar beside it; a run of messages from one
agent shares one avatar and one name; an agent that is answering is its
avatar beside three moving dots; the composer is a pill; a new message
glides into view. Every bubble is still a recorded message drawn by the
real renderer (agent_chat_render), which is what the fixture here uses.

Drawn in the office's own side column (office.html), which loads the same
stylesheet and script as the agents page, so the thread cannot differ
between the two.
"""
import http.server
import json
import pathlib
import re
import sys
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"
sys.path.insert(0, str(STATIC.parent))
import agent_chat_render as render                        # noqa: E402

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada",
     "meta": {"role": "Project manager", "toolIds": ["code"], "skillIds": []},
     "params": {}, "user_id": "me", "created_at": 1, "updated_at": 1},
    {"id": "agent-mia-77", "name": "Mia",
     "meta": {"role": "Receptionist", "toolIds": ["gmail"], "skillIds": []},
     "params": {}, "user_id": "me", "created_at": 2, "updated_at": 2},
]

THREAD = render.thread([
    {"role": "user", "content": "What did we decide about the launch?",
     "turn_id": "t1"},
    {"role": "assistant", "agent_name": "Ada", "content": "We moved it to **Thursday**."},
    {"role": "assistant", "agent_name": "Ada", "content": "Marketing wanted one more day."},
    {"role": "assistant", "agent_name": "Ada", "content": "I put it on the calendar."},
    {"role": "note", "content": "Ada asked Mia"},
    {"role": "assistant", "agent_name": "Mia", "content": "Inbox is clear."},
    {"role": "user", "content": "Can you draft the announcement?", "turn_id": "t2"},
])
#: What the stream delivers while Ada answers the second turn. Put into the
#: turn's status row after the thread has loaded, the way the round does
#: (turn_status swaps it out of band into a turn that is already on
#: screen); appended to the thread's own response it would address a turn
#: that is not in the document yet and be dropped.
WORKING = render.working("Ada")


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


def _serve(html: bytes):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?", 1)[0]
            body, kind = html, "text/html"
            if "/office/" in path:
                asset = STATIC / "office" / path.split("/office/", 1)[1]
            elif path.startswith("/tasks/static/"):
                rel = path.rsplit("/", 1)[1]
                asset = STATIC / rel if (STATIC / rel).is_file() else STATIC / "vendor" / rel
            else:
                asset = None
            if asset is not None:
                if not asset.is_file():
                    self.send_error(404, "no such asset: %s" % path)
                    return
                body = asset.read_bytes()
                kind = "text/css" if path.endswith(".css") else "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def page(browser):
    srv = _serve((STATIC / "office.html").read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            r.fulfill(status=204)
            return
        if "/chat/thread" in url:
            r.fulfill(status=200, content_type="text/html", body=THREAD)
            return
        if "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            body = {"activity": {}, "handoffs": []}
        elif "/agents/todo" in url:
            body = {"open": [], "done": []}
        elif "/agents/stats" in url:
            body = {"stats": {}}
        else:
            body = {"skills": []}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/agents/chat/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector("#agent-thread .am.agent", state="visible")
    pg.evaluate("h => { document.querySelector('#aturn-t2 .aturn-status').innerHTML = h;"
                " document.body.dispatchEvent(new CustomEvent('htmx:sseMessage')); }",
                WORKING)
    pg.wait_for_timeout(300)
    pg.errors = errors
    yield pg
    pg.close()
    srv.shutdown()


def _rgb(css):
    """rgb(r, g, b) or the color(srgb r g b) a color-mix() computes to."""
    nums = [float(v) for v in re.findall(r"[\d.]+", css)]
    if css.startswith("color(srgb"):
        return tuple(int(round(v * 255)) for v in nums[:3])
    return tuple(int(v) for v in nums[:3])


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = _lum(_rgb(a)), _lum(_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_the_page_loads_its_chat_scripts_without_error(page):
    assert page.errors == [], page.errors


def test_what_you_said_is_a_filled_bubble_on_the_right(page):
    got = page.locator("#agent-thread .am.user .ab").first.evaluate(
        "el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();"
        " const t = document.getElementById('agent-thread').getBoundingClientRect();"
        " return { bg: s.backgroundColor, fg: s.color, radius: s.borderTopLeftRadius,"
        "          tight: s.borderBottomRightRadius,"
        "          rightGap: t.right - r.right, leftGap: r.left - t.left }; }")
    assert _rgb(got["bg"]) != (0, 0, 0) and not got["bg"].startswith("rgba(0, 0, 0, 0)"), got
    assert got["rightGap"] < got["leftGap"], got
    assert got["radius"] == "18px" and got["tight"] == "5px", got
    assert _contrast(got["fg"], got["bg"]) >= 4.5, got


def test_what_an_agent_said_is_a_bubble_beside_its_avatar(page):
    row = page.locator('#agent-thread .am.agent[data-agent="Mia"]').first
    got = row.evaluate(
        "el => { const av = el.querySelector('.aav').getBoundingClientRect();"
        " const tx = el.querySelector('.atext'); const s = getComputedStyle(tx);"
        " const r = tx.getBoundingClientRect();"
        " return { avatarLeftOfText: av.right <= r.left, avatarRound: getComputedStyle(el.querySelector('.aav')).borderRadius,"
        "          bg: s.backgroundColor, radius: s.borderTopRightRadius,"
        "          who: el.querySelector('.awho').textContent }; }")
    assert got["avatarLeftOfText"], got
    assert got["avatarRound"] == "50%", got
    assert got["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"), got
    assert got["radius"] == "18px", got
    assert got["who"] == "Mia", got


def test_a_run_of_messages_from_one_agent_is_grouped(page):
    """Three answers in a row from Ada: one name, one avatar (on the last),
    and the corners between them tightened."""
    rows = page.locator('#agent-thread .am.agent[data-agent="Ada"]')
    assert rows.count() == 3
    classes = [rows.nth(i).get_attribute("class") for i in range(3)]
    assert "g-first" in classes[0] and "g-mid" in classes[1] and "g-last" in classes[2], classes
    shown = [rows.nth(i).locator(".aav").evaluate("el => getComputedStyle(el).visibility")
             for i in range(3)]
    assert shown == ["hidden", "hidden", "visible"], shown
    names = [rows.nth(i).locator(".awho").evaluate("el => getComputedStyle(el).display")
             for i in range(3)]
    assert names == ["block", "none", "none"], names
    corners = rows.nth(1).locator(".atext").evaluate(
        "el => [getComputedStyle(el).borderTopLeftRadius, getComputedStyle(el).borderBottomLeftRadius]")
    assert corners == ["5px", "5px"], corners


def test_a_message_from_someone_else_is_not_grouped_in(page):
    mia = page.locator('#agent-thread .am.agent[data-agent="Mia"]').first
    assert not re.search(r"\bg-(first|mid|last)\b", mia.get_attribute("class") or "")


def test_an_agent_that_is_answering_is_its_avatar_and_three_moving_dots(page):
    working = page.locator("#agent-thread .aworking").first
    assert working.locator(".aav").count() == 1
    assert working.locator(".atyping i").count() == 3
    assert working.locator(".atyping i").first.evaluate(
        "el => getComputedStyle(el).animationName") == "typing"
    assert "Ada is working" in working.inner_text()


def test_markdown_in_an_answer_is_rendered_in_the_office_too(page):
    """The office loaded no renderer, so an answer there showed its
    asterisks. The same scripts as the agents page now."""
    assert page.locator('#agent-thread .am.agent[data-agent="Ada"] .atext.md.done strong').count() == 1


def test_the_composer_is_a_pill(page):
    got = page.evaluate(
        "() => [getComputedStyle(document.querySelector('.ap-composer input[name=message]')).borderRadius,"
        "       getComputedStyle(document.querySelector('.ap-composer .btn')).borderRadius]")
    assert got == ["999px", "999px"], got


def test_a_new_message_arrives_rather_than_appears(page):
    names = page.evaluate(
        "() => [getComputedStyle(document.querySelector('.am.user')).animationName,"
        "       getComputedStyle(document.querySelector('.am.agent')).animationName]")
    assert names == ["msg-in-right", "msg-in-left"], names


def test_reduced_motion_stills_the_thread(page):
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(100)
    names = page.evaluate(
        "() => [getComputedStyle(document.querySelector('.am.user')).animationName,"
        "       getComputedStyle(document.querySelector('.atyping i')).animationName]")
    assert names == ["none", "none"], names


def test_the_thread_is_scrolled_to_its_newest_message(page):
    got = page.locator("#agent-thread").evaluate(
        "el => ({ top: el.scrollTop, max: el.scrollHeight - el.clientHeight })")
    assert got["max"] == 0 or got["top"] >= got["max"] - 2, got
