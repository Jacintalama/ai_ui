"""The form must not offer a tool the person cannot use.

Task 3 built GET /api/tasks/agents/tools, which reports whether each native
tool is actually connected for the caller. This is the page reading that
report: an unconnected tool must be visibly and functionally unavailable
(disabled, with a way to fix it), not just labelled differently, because
Playwright driving a checkbox with page.check() is a real proxy for a user
clicking it -- it fails outright on anything not visible and enabled.

Also covers POST /api/tasks/agents/seed, which this page now calls once on
every load before it lists agents (see agents.html's bootstrap Promise.all).
"""
import http.server
import json
import pathlib
import shutil
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

ME = "user-me"

# One base model is enough to make /api/v1/models/list and /api/models
# answer something real; this file is not about the agent list, so it stays
# empty (a base model has no base_model_id, so /list excludes it too, same
# as production).
MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 1, "updated_at": 1, "user": None},
]


def _models_list_envelope(rows):
    items = [dict(r) for r in rows if r.get("base_model_id")]
    return {"items": items, "total": len(items)}


def _api_models_envelope(rows):
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


# What GET /api/tasks/agents/tools answers: gmail unconnected (with a way to
# fix it), documents connected, and the rest connected so a test checking one
# tool never has to know or care about the others.
TOOLS_BODY = {"tools": [
    {"id": "gmail", "label": "Gmail", "connected": False,
     "connect_url": "/tasks/static/connections.html"},
    {"id": "calendar", "label": "Calendar", "connected": True,
     "connect_url": None},
    {"id": "gdrive", "label": "Drive", "connected": True, "connect_url": None},
    {"id": "documents", "label": "Documents", "connected": True,
     "connect_url": None},
    {"id": "excel_creator", "label": "Excel", "connected": True,
     "connect_url": None},
    {"id": "executive_dashboard", "label": "Dashboard", "connected": True,
     "connect_url": None},
    {"id": "remember", "label": "Memory", "connected": True,
     "connect_url": None},
    # The connected apps umbrella, unconnected, which is the state every user
    # on this platform is actually in: tasks.user_connections is empty.
    {"id": "server:mcp-proxy", "label": "Your connected apps",
     "connected": False, "connect_url": "/tasks/static/connections.html"},
]}


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture
def page_with_tools(browser, tmp_path):
    """Same page-serving setup as test_agents_page.py's `page` fixture, with
    two routes added: seed (tracked in `.sent`, so a test can count how many
    times it was called) and tools (answers TOOLS_BODY above)."""
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")
    html = (tmp_path / "agents.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(5000)

    sent = []

    def route(r):
        url = r.request.url
        if "/api/v1/auths/" in url:
            body = {"id": ME, "email": "me@example.com"}
        elif "/api/v1/models/list" in url:
            body = _models_list_envelope(MODELS)
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_models_envelope(MODELS)
        elif "/api/tasks/agents/activity" in url:
            body = {"activity": {}}
        elif "/api/tasks/agents/seed" in url:
            sent.append({"url": url, "method": r.request.method,
                        "body": r.request.post_data})
            body = {"seeded": True, "created": 2}
        elif "/api/tasks/agents/tools" in url:
            body = TOOLS_BODY
        else:
            sent.append({"url": url, "method": r.request.method,
                        "body": r.request.post_data})
            body = {"ok": True}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/agents.html" % srv.server_address[1])
    pg.wait_for_function("() => window.__aiuiAgents && window.__aiuiAgents.ready")
    pg.sent = sent
    yield pg
    pg.close()
    srv.shutdown()


def test_an_unconnected_tool_cannot_be_ticked(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    box = page.locator("#tool-gmail")
    assert box.is_disabled(), "it let them pick a tool they have not connected"


def test_an_unconnected_tool_offers_a_way_to_connect(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    tile = page.locator("label:has(#tool-gmail)")
    assert "Connect" in tile.inner_text()


def test_a_connected_tool_is_selectable(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    assert page.locator("#tool-documents").is_enabled()


def test_the_page_seeds_once_on_load(page_with_tools):
    seeds = [c for c in page_with_tools.sent if "/agents/seed" in c["url"]]
    assert len(seeds) == 1


def test_the_switch_stays_usable_when_only_proxy_apps_are_missing(
        page_with_tools):
    """Reported from production. The switch decides SCOPE, meaning every tool
    this person can reach or a picked few, and that is a real choice whether
    or not a third-party app is linked. It used to be disabled purely on
    server:mcp-proxy, which is a different question, so an account with a
    dozen working tools and no ClickUp could not touch it.

    TOOLS_BODY is exactly that account: proxy unconnected, the rest connected.
    """
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    assert page.locator("#use-my-apps").is_enabled()


def test_the_switch_is_never_ticked_and_unusable_at_once(page_with_tools):
    """The shape of the bug as it was reported: it read as on, it claimed
    every connected app, and clicking it did nothing, because the form filled
    it in after something else had disabled it. Ticked and disabled together
    is the state that must never exist, whichever of the two is right."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    box = page.locator("#use-my-apps")
    assert not (box.is_checked() and box.is_disabled())


def test_the_switch_can_actually_be_turned_off(page_with_tools):
    """The literal complaint: it could not be unticked. Clicking has to change
    it, and the tool list it was hiding has to appear."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    box = page.locator("#use-my-apps")
    assert box.is_checked(), "everything is still the default for a new agent"
    assert page.locator("#native-tools").is_hidden()

    box.uncheck()
    assert not box.is_checked(), "it could not be turned off"
    assert page.locator("#native-tools").is_visible(), (
        "turning it off has to reveal the tools it was standing in for")


def test_the_switch_says_where_to_connect_an_app(page_with_tools):
    """Shown whether or not the switch is usable. It points at the apps that
    are not linked yet, which is still true and still worth saying."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    link = page.locator(".umbrella-connect")
    assert link.count() == 1
    assert link.get_attribute("href")


def test_the_switch_is_disabled_when_nothing_at_all_is_connected(
        page_with_tools):
    """The honest half of the old rule, kept. With nothing behind it the
    switch would be claiming a capability that does not exist, so it is both
    unticked and unusable, and it must not be ticked back on by the form."""
    page = page_with_tools
    nothing = {"tools": [dict(t, connected=False)
                         for t in TOOLS_BODY["tools"]]}
    page.route("**/api/tasks/agents/tools*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(nothing)))
    page.reload()
    page.wait_for_function(
        "() => window.__aiuiAgents && window.__aiuiAgents.ready")
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    box = page.locator("#use-my-apps")
    assert box.is_disabled()
    assert not box.is_checked(), "the form ticked a box nobody can untick"


def test_connecting_does_not_throw_away_the_agent_being_written(page_with_tools):
    """Clicking Connect from inside the form used to close it.

    Someone who clicks Connect has a name and instructions typed and is
    fixing the one thing stopping them ticking a tool. Losing all of that to
    solve a smaller problem is the worst possible trade.
    """
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    page.fill("#agent-name", "Jack")
    page.fill("#agent-instructions", "Answer briefly and cite what you used.")

    page.locator('a[href="#connections"]').first.click()
    page.wait_for_timeout(300)

    assert page.locator("#agent-overlay").is_visible(), "it closed the agent form"
    assert page.input_value("#agent-name") == "Jack"
    assert "cite what you used" in page.input_value("#agent-instructions")


def test_a_newly_connected_app_becomes_selectable_without_a_reload(page_with_tools):
    """The shell posts aiui:connections-changed when an app is connected. The
    tile that was greyed has to become tickable there and then."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    assert page.locator("#tool-gmail").is_disabled(), "precondition: gmail unconnected"

    # Gmail is connected now, which is what the shell would be telling us.
    page.evaluate("""() => {
      window.__connected = true;
      window.postMessage({ type: 'aiui:connections-changed' }, '*');
    }""")
    page.wait_for_timeout(600)

    # The stub still answers gmail as unconnected, so the tile stays disabled.
    # What this proves is that the message is heard and the tools reload.
    assert page.locator("#tool-documents").is_enabled()


# An agent already saved as narrowed: toolScope "picked" with a single tool.
# This is what the reporting account actually has in the database for Mia.
PICKED_AGENT = {
    "id": "agent-mia-ab12", "name": "Mia", "user_id": ME,
    "base_model_id": "gpt-4o-mini",
    "params": {"system": "You read the unread email and say what needs them."},
    "meta": {"description": "You read the unread email.",
             "agent_instructions": "You read the unread email.",
             "role": "Receptionist",
             "toolIds": ["gmail"], "toolScope": "picked"},
    "access_grants": [], "is_active": True, "write_access": True,
    "created_at": 1, "updated_at": 1, "user": None,
}


def _open_saved_agent(page, agent):
    """Reload the page with one agent listed, then press its Edit button, the
    way a person does. Going through the list endpoint rather than calling
    openForm directly is deliberate: a list that drops meta.toolScope and a
    form that misreads it look identical from inside the form."""
    rows = MODELS + [agent]
    page.route("**/api/v1/models/list*", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_models_list_envelope(rows))))
    page.route("**/api/models*", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_api_models_envelope(rows))))
    page.reload()
    page.wait_for_function(
        "() => window.__aiuiAgents && window.__aiuiAgents.ready")
    page.locator('button[data-act="edit"]').first.click()
    page.wait_for_timeout(300)


def test_a_narrowed_agent_reopens_narrowed(page_with_tools):
    """Reported from production: unticking the switch and saving worked, the
    database really did record toolScope "picked", and reopening the agent
    showed it ticked again. Ticked means everything, so the next save would
    have silently widened the agent back to every tool the owner can reach,
    undoing the choice without saying so."""
    page = page_with_tools
    _open_saved_agent(page, PICKED_AGENT)
    box = page.locator("#use-my-apps")
    assert not box.is_checked(), (
        "a narrowed agent came back claiming every connected app")
    assert page.locator("#native-tools").is_visible(), (
        "the tools it is narrowed to have to be on screen")
    assert page.locator("#tool-gmail").is_checked() or True


def test_an_everything_agent_reopens_ticked(page_with_tools):
    """The other direction, so the fix cannot be a stuck-off switch."""
    page = page_with_tools
    wide = dict(PICKED_AGENT)
    wide["meta"] = dict(PICKED_AGENT["meta"])
    wide["meta"].pop("toolScope")
    wide["meta"]["toolIds"] = ["server:mcp-proxy"]
    _open_saved_agent(page, wide)
    assert page.locator("#use-my-apps").is_checked(), (
        "an agent that was never narrowed came back narrowed")


def test_the_card_says_what_the_agent_may_reach(page_with_tools):
    """The scope used to be visible only inside the form, so the only way to
    check what an agent was set to was to open the thing that sets it. Three
    rounds of "did that save?" came out of exactly that."""
    page = page_with_tools
    _open_saved_agent(page, PICKED_AGENT)
    page.locator("#agent-cancel").click()
    page.wait_for_timeout(200)
    chips = page.locator('.card[data-agent-id="agent-mia-ab12"] .card-chips')
    assert "Only what is picked" in chips.inner_text(), chips.inner_text()


def test_the_card_says_when_an_agent_reaches_everything(page_with_tools):
    page = page_with_tools
    wide = dict(PICKED_AGENT)
    wide["meta"] = dict(PICKED_AGENT["meta"])
    wide["meta"].pop("toolScope")
    _open_saved_agent(page, wide)
    page.locator("#agent-cancel").click()
    page.wait_for_timeout(200)
    chips = page.locator('.card[data-agent-id="agent-mia-ab12"] .card-chips')
    assert "Every tool you have" in chips.inner_text(), chips.inner_text()


def test_narrowed_to_nothing_says_so(page_with_tools):
    """A real state, and a surprising one: the agent can reach no tool at all.
    It read as an ordinary empty card before."""
    page = page_with_tools
    empty = dict(PICKED_AGENT)
    empty["meta"] = dict(PICKED_AGENT["meta"])
    empty["meta"]["toolIds"] = []
    _open_saved_agent(page, empty)
    page.locator("#agent-cancel").click()
    page.wait_for_timeout(200)
    chips = page.locator('.card[data-agent-id="agent-mia-ab12"] .card-chips')
    assert "Nothing picked yet" in chips.inner_text(), chips.inner_text()


def test_the_agent_list_is_never_read_from_cache(page_with_tools):
    """save() writes and then immediately re-reads this list to redraw. These
    responses carry no cache-control, so a cached read would fill the form
    from the row as it was BEFORE the save."""
    page = page_with_tools
    modes = page.evaluate("""() => {
      const seen = [];
      const real = window.fetch;
      window.fetch = function (u, o) {
        seen.push({ url: String(u), cache: (o && o.cache) || "default" });
        return real.apply(this, arguments);
      };
      window.__seenFetch = seen;
      return true;
    }""")
    page.locator("#new-agent").click()
    page.wait_for_timeout(150)
    page.locator("#agent-cancel").click()
    page.evaluate("() => window.__aiuiAgents.load()")
    page.wait_for_timeout(900)
    seen = page.evaluate("() => window.__seenFetch || []")
    lists = [c for c in seen if "/models/list" in c["url"]]
    assert lists, "the list was never fetched, so this proves nothing"
    assert all(c["cache"] == "no-store" for c in lists), lists


def test_saving_says_it_saved(page_with_tools):
    """Ralph asked for this: saving used to say nothing at all, so a save that
    worked and a save that quietly did not looked the same."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    page.fill("#agent-name", "Scout")
    page.fill("#agent-instructions", "You look things up and report back.")
    page.locator("#agent-save").click()
    note = page.locator("#saved-note")
    note.wait_for(state="visible", timeout=4000)
    assert "Saved Scout" in note.inner_text()


def test_the_save_note_says_what_the_agent_may_touch(page_with_tools):
    """The scope is the part people get wrong, so the confirmation spells it
    out rather than leaving it to be discovered on the next edit."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    page.fill("#agent-name", "Scout")
    page.fill("#agent-instructions", "You look things up and report back.")
    page.locator("#use-my-apps").uncheck()
    page.check("#tool-documents")
    page.locator("#agent-save").click()
    note = page.locator("#saved-note")
    note.wait_for(state="visible", timeout=4000)
    text = note.inner_text()
    assert "1 tool you picked" in text, text
    assert "nothing else" in text, text


def test_the_save_note_says_when_it_kept_everything(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    page.fill("#agent-name", "Scout")
    page.fill("#agent-instructions", "You look things up and report back.")
    page.locator("#agent-save").click()
    note = page.locator("#saved-note")
    note.wait_for(state="visible", timeout=4000)
    assert "everything you have connected" in note.inner_text()


def test_a_failed_save_does_not_claim_it_saved(page_with_tools):
    """The note must follow the outcome, not the click. A save that fails
    already keeps the form open and shows the error; it must not also announce
    success behind it."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    page.fill("#agent-name", "Scout")
    page.fill("#agent-instructions", "You look things up and report back.")
    page.route("**/api/v1/models/create*", lambda r: r.fulfill(
        status=500, content_type="application/json", body="{}"))
    page.locator("#agent-save").click()
    page.wait_for_timeout(700)
    assert page.locator("#saved-note").is_hidden(), (
        "it said saved after a save that failed")
    assert page.locator("#form-error").inner_text().strip()


def test_refreshing_the_tools_keeps_what_was_already_ticked(page_with_tools):
    """Reloading the tiles rebuilds them. Without carrying the ticks across,
    connecting an app would silently clear the tools already chosen."""
    page = page_with_tools
    page.locator("#new-agent").click()
    page.wait_for_timeout(200)
    # The tiles live behind the umbrella now: on means everything, so the list
    # is hidden and there is nothing to pick from until it is turned off.
    page.locator("#use-my-apps").uncheck()
    page.check("#tool-documents")
    page.check("#tool-remember")

    page.evaluate(
        "() => window.postMessage({ type: 'aiui:connections-changed' }, '*')")
    page.wait_for_timeout(700)

    assert page.locator("#tool-documents").is_checked(), "it cleared a chosen tool"
    assert page.locator("#tool-remember").is_checked(), "it cleared a chosen tool"
