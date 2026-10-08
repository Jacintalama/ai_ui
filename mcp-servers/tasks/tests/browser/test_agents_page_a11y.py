"""Contrast, focus and dialogs on the agents page.

Measured on 2026-10-05 in Chromium against this page with its real
stylesheet and panel script:

- --muted (#74747e) was 3.87:1 on --surface-2, and the composer placeholder
  was the browser's own #757575, 3.88:1.
- Every .btn, the search boxes and the checkboxes computed to Arial.
- Tab reached the search box and the composer with outline: none and nothing
  in its place, and every button with the browser's ring in rgb(16, 16, 16)
  on a near black page.
- The agent form had no dialog role and left focus on the button behind it.
- Connections opened from inside the form drew UNDER it (both overlays at
  z-index 50, the form later in the markup), and Escape closed neither.

Rendered, not read: contrast and focus are computed styles, and a rule that
loses on specificity reads exactly like one that wins.
"""
import http.server
import json
import pathlib
import re
import threading

import pytest

import agent_chat_render as render

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

ME = "user-me"
#: DESIGN.md Switchboard Periwinkle, as getComputedStyle reports it.
ACCENT = "rgb(124, 140, 255)"

AGENTS = [
    {"id": "agent-ada-0001", "name": "Ada", "user_id": ME,
     "base_model_id": "gpt-4o-mini",
     "params": {"system": "You are Ada. Project manager."},
     "meta": {"role": "Project manager", "toolIds": []},
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 1, "updated_at": 1,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}},
]

BASE_MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 0, "updated_at": 0, "user": None},
]

#: The connected apps umbrella unconnected, so the form carries its "Connect
#: an app" link: the one real way Connections opens ON TOP of the form.
TOOLS = {"tools": [
    {"id": "gmail", "label": "Gmail", "connected": True, "connect_url": None},
    {"id": "server:mcp-proxy", "label": "Your connected apps",
     "connected": False, "connect_url": ""},
]}

SKILLS = {"skills": [
    {"name": "inbox-triage", "tags": ["email"], "tools": [],
     "description": "Sort unread mail into what needs a reply today."},
]}


def _api_envelope(rows):
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


def _rgb(css):
    css = css.strip()
    if css.startswith("#"):
        h = css[1:]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(float(v)) for v in re.findall(r"[\d.]+", css)[:3])


def _contrast(fg, bg):
    """WCAG 2 contrast ratio between two CSS colours."""
    def lum(colour):
        lin = []
        for v in _rgb(colour):
            v /= 255
            lin.append(v / 12.92 if v <= 0.03928
                       else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:                            # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


# The real stylesheet and the real panel script, as test_office_inline.py
# serves them. The composer's focus style lives in agent-chat.css and the
# clear confirm opens and closes in agent-chat.js, so a fixture that answered
# either with a placeholder would test an unstyled, half wired page.
@pytest.fixture(scope="module")
def server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            path = self.path.split("?")[0]
            name = path.rsplit("/", 1)[-1]
            kind = "text/html"
            if name in ("agent-chat.css", "agent-chat.js"):
                body = (STATIC / name).read_bytes()
                kind = ("text/css" if name.endswith(".css")
                        else "text/javascript")
            elif name.endswith(".js"):
                # Vendored htmx, marked and DOMPurify. Not under test, and
                # an empty body keeps htmx from swapping stub JSON into the
                # thread.
                body, kind = b"", "text/javascript"
            elif path.startswith("/tasks/office"):
                # The dock frames the office. A blank page keeps this file
                # about the agents page.
                body = b"<!doctype html><title>office</title>"
            else:
                body = (STATIC / "agents.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def page(browser, server):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(5000)

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif url.rstrip("/").endswith("/api/tasks/agents/memory"):
            body = {"counts": {}}
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/skills" in url:
            body = SKILLS
        elif "/agents/tools" in url:
            body = TOOLS
        elif "/api/v1/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_envelope(AGENTS + BASE_MODELS)
        else:
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % server.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    pg.wait_for_selector('[data-agent-id="agent-ada-0001"]')
    yield pg
    pg.close()


def _active(page):
    return page.evaluate(
        "() => { const e = document.activeElement;"
        " return { id: e.id, cls: typeof e.className === 'string'"
        " ? e.className : '', act: e.dataset ? (e.dataset.act || '') : '' }; }")


def _open_form(page):
    page.locator("#new-agent").click()
    page.wait_for_selector("#agent-form", state="visible")


# --- contrast and the page font ----------------------------------------------

def test_muted_text_passes_aa_on_every_surface(page):
    """DESIGN.md: Muted is #8b8b95, at least 5.30:1 on every surface."""
    tokens = page.evaluate(
        "() => { const s = getComputedStyle(document.documentElement);"
        " return Object.fromEntries(['--muted', '--bg', '--surface',"
        " '--surface-2'].map(k => [k, s.getPropertyValue(k).trim()])); }")
    for surface in ("--bg", "--surface", "--surface-2"):
        ratio = _contrast(tokens["--muted"], tokens[surface])
        assert ratio >= 4.5, "%s on %s (%s) is %.2f:1" % (
            tokens["--muted"], surface, tokens[surface], ratio)


def test_muted_text_on_screen_is_readable(page):
    """The token is only half of it: what a person reads is the computed
    colour on the computed background. The composer placeholder ignored the
    token entirely and used the browser's own grey."""
    got = page.evaluate(
        "() => { const i = document.querySelector("
        "'.ap-composer input[name=message]');"
        " const sub = document.getElementById('ap-sub');"
        " return { ph: getComputedStyle(i, '::placeholder').color,"
        " field: getComputedStyle(i).backgroundColor,"
        " sub: getComputedStyle(sub).color,"
        " panel: getComputedStyle(document.querySelector('.agent-panel'))"
        ".backgroundColor }; }")
    assert got["ph"] == "rgb(139, 139, 149)", got
    assert _contrast(got["ph"], got["field"]) >= 4.5, got
    assert _contrast(got["sub"], got["panel"]) >= 4.5, got


def test_no_control_falls_back_to_arial(page):
    """DESIGN.md: buttons inherit the family; the Arial fallback is a bug.
    Controls in the hidden dialogs count too: their style is computed all
    the same."""
    odd = page.evaluate(
        "() => { const want = getComputedStyle(document.body).fontFamily;"
        " return [...document.querySelectorAll("
        "'button, input, select, textarea')]"
        ".filter(e => getComputedStyle(e).fontFamily !== want)"
        ".map(e => (e.id || e.className || e.tagName) + ': '"
        " + getComputedStyle(e).fontFamily); }")
    assert odd == [], odd


# --- focus ---------------------------------------------------------------------

#: What the focused element draws, and the first ancestor that would cut its
#: ring off at the side (overflow other than visible, measured on the padding
#: box, which is where the clip is).
FOCUSED_JS = """() => {
  const e = document.activeElement;
  const s = getComputedStyle(e);
  const r = e.getBoundingClientRect();
  let clip = null;
  for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
    if (getComputedStyle(p).overflowX === 'visible') continue;
    const c = p.getBoundingClientRect();
    const left = c.left + p.clientLeft, right = left + p.clientWidth;
    if (r.left - 4 < left - 0.5 || r.right + 4 > right + 0.5) {
      clip = p.id || p.className; break;
    }
  }
  return { what: e.tagName + '#' + e.id + '.' +
             (typeof e.className === 'string' ? e.className : ''),
           tag: e.tagName, id: e.id,
           ring: [s.outlineStyle, s.outlineWidth, s.outlineColor,
                  s.outlineOffset],
           after: getComputedStyle(e, '::after').backgroundColor, clip };
}"""


def test_every_stop_on_the_tab_path_draws_the_periwinkle_ring(page):
    """One ring for everything (DESIGN.md: 2px periwinkle, 2px offset), and
    not cut off by the scrolling column it sits in."""
    page.locator("body").click(position={"x": 5, "y": 5})
    seen = []
    for _ in range(16):
        page.keyboard.press("Tab")
        f = page.evaluate(FOCUSED_JS)
        if f["tag"] in ("BODY", "IFRAME"):
            continue
        if f["id"] == "ap-resize":
            # Its mark fades in over 0.12s, and a computed style read mid
            # transition reports the starting colour.
            page.wait_for_timeout(250)
            f = page.evaluate(FOCUSED_JS)
        seen.append(f)
    assert len(seen) >= 8, [f["what"] for f in seen]
    for f in seen:
        if f["id"] == "ap-resize":
            # A full height drag strip between the columns. Its focus mark is
            # the 2px accent rule it already draws, which is a replacement,
            # not an outline: none with nothing in its place.
            assert f["after"] == ACCENT, f
            continue
        assert f["ring"] == ["solid", "2px", ACCENT, "2px"], f
        assert f["clip"] is None, f


def test_a_focused_composer_looks_different_from_an_idle_one(page):
    box = page.locator(".ap-composer input[name=message]")
    idle = box.evaluate(
        "e => [getComputedStyle(e).borderTopColor,"
        " getComputedStyle(e).outlineStyle]")
    box.focus()
    now = box.evaluate(
        "e => { const s = getComputedStyle(e); return [s.borderTopColor,"
        " s.outlineStyle, s.outlineWidth, s.outlineColor, s.outlineOffset]; }")
    assert idle[0] != ACCENT and idle[1] == "none", idle
    assert now == [ACCENT, "solid", "2px", ACCENT, "2px"], now


def test_the_skill_search_is_a_styled_field_not_a_white_box(page):
    _open_form(page)
    page.locator("#skills-toggle").click()
    got = page.locator("#skill-search").evaluate(
        "e => { const s = getComputedStyle(e); return [s.backgroundColor,"
        " s.borderTopColor, s.color, s.fontSize]; }")
    # --surface-2, --border-2, --text, and the other fields' 13px.
    assert got == ["rgb(23, 23, 26)", "rgb(46, 46, 54)",
                   "rgb(237, 237, 238)", "13px"], got


@pytest.mark.parametrize("field", ["#agent-name", "#agent-instructions",
                                   "#agent-base", "#skill-search"])
def test_a_focused_form_field_shows_the_ring_and_the_border(page, field):
    """Reached by keyboard, the way a person tabbing through the form gets
    there, so :focus-visible applies to the select as it would for them."""
    _open_form(page)
    page.locator("#skills-toggle").click()
    page.locator(field).focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    assert _active(page)["id"] == field[1:], _active(page)
    got = page.locator(field).evaluate(
        "e => { const s = getComputedStyle(e); return [s.outlineStyle,"
        " s.outlineWidth, s.outlineColor, s.borderTopColor]; }")
    assert got == ["solid", "2px", ACCENT, ACCENT], (field, got)


# --- dialogs -------------------------------------------------------------------

@pytest.mark.parametrize("dialog, title", [("#agent-form", "New agent"),
                                           ("#connections-panel", "Connections"),
                                           ("#ap-clear-modal",
                                            "Clear this conversation?")])
def test_each_dialog_is_announced_as_one(page, dialog, title):
    el = page.locator(dialog)
    assert el.get_attribute("role") == "dialog", dialog
    assert el.get_attribute("aria-modal") == "true", dialog
    label = el.get_attribute("aria-labelledby")
    assert label, dialog
    assert page.locator("#" + label).inner_text().strip() == title


def test_opening_the_form_moves_focus_in_and_cancel_hands_it_back(page):
    page.locator("#new-agent").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#agent-form", state="visible")
    assert _active(page)["id"] == "agent-name", _active(page)
    page.locator("#agent-cancel").click()
    assert page.locator("#agent-overlay").is_hidden()
    assert _active(page)["id"] == "new-agent", _active(page)


def test_escape_closes_the_form_and_returns_to_the_edit_button(page):
    edit = page.locator('[data-agent-id="agent-ada-0001"] [data-act="edit"]')
    edit.click()
    page.wait_for_selector("#agent-form", state="visible")
    assert _active(page)["id"] == "agent-name", _active(page)
    page.keyboard.press("Escape")
    assert page.locator("#agent-overlay").is_hidden(), "Escape left the form open"
    assert _active(page)["act"] == "edit", _active(page)


def test_connections_opened_from_the_form_sits_on_top_of_it(page):
    _open_form(page)
    page.locator("#agent-form a.umbrella-connect").click()
    page.wait_for_selector("#connections-panel", state="visible")
    top = page.evaluate(
        "() => { const p = document.getElementById('connections-panel')"
        ".getBoundingClientRect();"
        " const e = document.elementFromPoint(p.left + p.width / 2, p.top + 12);"
        " if (!e) return null;"
        " if (e.closest('#connections-panel')) return 'connections';"
        " if (e.closest('#agent-form')) return 'agent-form';"
        " return e.tagName; }")
    assert top == "connections", top


def test_escape_closes_only_the_top_most_dialog(page):
    """Connections over the form. One Escape closes Connections and keeps
    the half written agent; the next closes the form."""
    _open_form(page)
    page.fill("#agent-name", "Jack")
    page.locator("#agent-form a.umbrella-connect").click()
    page.wait_for_selector("#connections-panel", state="visible")
    assert page.evaluate(
        "() => !!document.activeElement.closest('#connections-panel')"), (
        "focus stayed behind the panel")

    page.keyboard.press("Escape")
    assert page.locator("#connections-overlay").is_hidden()
    assert page.locator("#agent-overlay").is_visible(), "one Escape closed both"
    assert page.input_value("#agent-name") == "Jack"
    # Closing re-reads the tools and redraws the link that opened the panel,
    # so focus lands on its replacement once that is done.
    page.wait_for_function(
        "() => document.activeElement.classList.contains('umbrella-connect')")

    page.keyboard.press("Escape")
    assert page.locator("#agent-overlay").is_hidden()
    assert _active(page)["id"] == "new-agent", _active(page)


def test_escape_closes_the_clear_confirm_and_returns_to_clear(page):
    """Already true before the Escape handlers were merged: kept as a pin,
    because the merge moved this case out of agent-chat.js."""
    page.locator("#ap-clear").click()
    page.wait_for_selector("#ap-clear-modal", state="visible")
    assert _active(page)["id"] == "ap-clear-cancel", _active(page)
    page.keyboard.press("Escape")
    assert page.locator("#ap-clear-overlay").is_hidden()
    assert _active(page)["id"] == "ap-clear", _active(page)


def test_escape_closes_an_open_card_menu_and_returns_to_its_button(page):
    more = page.locator('[data-agent-id="agent-ada-0001"] [data-act="more"]')
    more.click()
    menu = page.locator('[data-agent-id="agent-ada-0001"] .more-menu')
    assert menu.is_visible()
    page.keyboard.press("Escape")
    assert menu.is_hidden()
    assert _active(page)["act"] == "more", _active(page)


# --- Task 6: one type scale, a reading width, solid avatars ------------------
#
# DESIGN.md: only 12, 13, 14, 16 and 20px exist; message text sits in a
# centred column at most 760px wide and is capped at 68ch; each agent is one
# solid hsl(hue 45% 32%) avatar with white letters, and its hue appears
# nowhere else, so a card's border is the neutral --border.

SIZES = {"12px", "13px", "14px", "16px", "20px"}

#: A conversation drawn by the real renderer, so the thread's own classes
#: (.aturn, .awho, .atext, .aquote, .afail, .aav) are the ones on screen.
LONG = " ".join(["This answer runs long on purpose, so the line length shows."] * 12)
CALLS = [{"function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]
THREAD = render.thread([
    {"role": "user", "content": "What did we decide about the launch? " * 6,
     "turn_id": "aaa111"},
    {"role": "note", "content": "Ada asked Mia"},
    {"role": "assistant", "agent_name": "Ada", "content": LONG,
     "replying_to": "What did we decide about the launch?"},
    {"role": "failure", "agent_name": "Mia", "reason": "It ran out of time.",
     "fix": "Ask again in a minute."},
    {"role": "assistant", "agent_name": "Mia", "content": "",
     "awaiting": {"ask_id": "ask-1", "calls": CALLS}},
])


def _draw_thread(page):
    page.evaluate("h => { document.getElementById('agent-thread').innerHTML = h; }",
                  THREAD)


def _sizes_on_screen(page):
    """{font-size: [what uses it]} for every element that is rendered."""
    return page.evaluate(
        "() => { const out = {};"
        " for (const e of document.querySelectorAll('body *')) {"
        "  if (!e.getClientRects().length) continue;"
        "  const s = getComputedStyle(e);"
        "  if (s.visibility === 'hidden') continue;"
        "  const who = e.id || e.getAttribute('class') || e.tagName;"
        "  (out[s.fontSize] = out[s.fontSize] || []).push(who); }"
        " return out; }")


def _colour_of(page, css):
    """What the browser computes for a CSS colour on this page."""
    return page.evaluate(
        "css => { const d = document.createElement('div');"
        " d.style.color = css; document.body.appendChild(d);"
        " const c = getComputedStyle(d).color; d.remove(); return c; }", css)


def test_only_the_five_sizes_are_used(page):
    assert page.locator("#agent-details").is_visible(), "details are not open"
    _draw_thread(page)
    _open_form(page)
    odd = {k: v[:6] for k, v in _sizes_on_screen(page).items() if k not in SIZES}
    assert not odd, odd
    page.locator("#agent-cancel").click()
    page.locator("#open-connections").click()
    page.wait_for_selector("#connections-panel", state="visible")
    odd = {k: v[:6] for k, v in _sizes_on_screen(page).items() if k not in SIZES}
    assert not odd, odd


def test_the_stylesheets_declare_only_the_five_sizes():
    """The rendered check sees one state of the page. This one sees every
    rule, including the ones for states nobody opened in that test."""
    sources = {"agents.html": (STATIC / "agents.html").read_text(encoding="utf-8"),
               "agent-chat.css": (STATIC / "agent-chat.css").read_text(encoding="utf-8")}
    odd = []
    for name, text in sources.items():
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for value in re.findall(r"font-size:\s*([^;\"'}]+)", text):
            value = value.strip()
            if value != "inherit" and value not in SIZES:
                odd.append((name, value))
    assert not odd, odd


def test_messages_have_a_reading_width(page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    _draw_thread(page)
    got = page.evaluate(
        "() => { const t = document.getElementById('agent-thread').getBoundingClientRect();"
        " const ch = el => { const p = document.createElement('span');"
        "  p.style.cssText = 'display:inline-block;width:68ch';"
        "  el.appendChild(p); const w = p.getBoundingClientRect().width;"
        "  p.remove(); return w; };"
        " const turn = document.querySelector('.aturn').getBoundingClientRect();"
        " const text = document.querySelector('.am.agent .atext');"
        " const mine = document.querySelector('.am.user .ab');"
        " return { thread: [t.left, t.right], turn: [turn.left, turn.right, turn.width],"
        "  text: text.getBoundingClientRect().width, textCap: ch(text),"
        "  mine: mine.getBoundingClientRect().width, mineCap: ch(mine) }; }")
    left, right, width = got["turn"]
    assert width <= 760.5, got
    # Centred in the conversation, not pinned to its left edge.
    assert abs((left - got["thread"][0]) - (got["thread"][1] - right)) <= 12, got
    assert got["text"] <= min(760, got["textCap"]) + 0.5, got
    assert got["mine"] <= got["mineCap"] + 0.5, got


def test_avatars_are_solid(page):
    """No gradient anywhere an agent's mark is drawn: the list, the card and
    the thread (whose avatar comes from agent_chat_render)."""
    _draw_thread(page)
    hue = page.evaluate("() => window.__aiuiAgents.avatarHue('Ada')")
    solid = _colour_of(page, "hsl(%d 45%% 32%%)" % hue)
    for sel in ('#roster-list .roster-row[data-agent-id="agent-ada-0001"] .roster-av',
                '#my-agents [data-agent-id="agent-ada-0001"] .avatar',
                "#agent-thread .am.agent .aav"):
        style = page.locator(sel).first.evaluate(
            "e => { const s = getComputedStyle(e);"
            " return [s.backgroundImage, s.backgroundColor, s.color]; }")
        assert style == ["none", solid, "rgb(255, 255, 255)"], (sel, style)


def test_a_cards_border_is_the_neutral_border(page):
    """The hue is the avatar's alone (DESIGN.md, Agent identity): a card is
    framed by --border, and hovering it brings up --border-2, not a tint."""
    card = page.locator('#my-agents .card[data-agent-id="agent-ada-0001"]')
    border = _colour_of(page, "var(--border)")
    assert border == "rgb(36, 36, 42)", border
    assert card.evaluate("e => getComputedStyle(e).borderTopColor") == border
    assert card.evaluate("e => getComputedStyle(e).borderLeftColor") == border
    card.hover()
    page.wait_for_timeout(250)
    assert card.evaluate("e => getComputedStyle(e).borderTopColor") == (
        _colour_of(page, "var(--border-2)"))
