"""What the Agents page shows and what it sends.

An agent is an Open WebUI model row, so almost every bug here is a shape bug:
the wrong toolIds, instructions in the wrong place, or somebody else's agent
appearing in your list. Those are invisible to a test that reads copy, so the
page is rendered and driven.

The API is stubbed. That is a known blind spot and it is why the plan also
requires a real create-and-delete round trip during verification: a stub
answers whatever it is asked, which is exactly how a card requesting thumb.png
from a route serving thumb.jpg passed a full round of tests.
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
OTHER = "user-someone-else"

# A name that runs script if the page ever stops escaping. Owned by someone
# else on purpose, so the "your agents" list stays exactly one card.
HOSTILE_NAME = '<img src=x onerror="window.__pwned=1">'

# Flat rows, which is the shape GET /api/v1/models/list returns. gpt-4o-mini is
# a plain base model: it has no base_model_id, so /list never returns it, while
# /api/models does. Both envelopes below are derived from this one list so the
# stub cannot drift away from what the server actually sends.
MODELS = [
    {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 1, "updated_at": 1, "user": None},
    {"id": "agent-mine-a1b2", "name": "Researcher",
     "user_id": ME, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You research things carefully."},
     "meta": {"description": "mine", "toolIds": ["server:mcp-proxy"]},
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 2, "updated_at": 2,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}},
    # A second agent owned by ME. Without it, "delete the agent that was
    # clicked" and "delete the first agent in the list" are indistinguishable,
    # and a mutant that always deletes state.agents[0] passes.
    {"id": "agent-mine-second-c5d6", "name": "Secondagent",
     "user_id": ME, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You do the second thing."},
     "meta": {"description": "mine too", "toolIds": []},
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 6, "updated_at": 6,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}},
    {"id": "agent-shared-c3d4", "name": "Summariser",
     "user_id": OTHER, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You summarise meetings."},
     # A wildcard read grant is what actually makes an agent visible to
     # everybody, and it is what the page reads to show the shared badge.
     # A ready-made agent also stores its instructions in meta, because the
     # list endpoint blanks params for anyone without write access and that is
     # every user except its owner. Task 8 writes both.
     "meta": {"description": "platform", "toolIds": [],
              "agent_instructions": "You summarise meetings."},
     "access_grants": [{"principal_type": "user", "principal_id": "*",
                        "permission": "read"}],
     "is_active": True, "write_access": False,
     "created_at": 3, "updated_at": 3,
     "user": {"id": OTHER, "name": "Someone", "email": "other@example.com"}},
    # A ready-made agent whose instructions cannot be read at all: params is
    # blanked because it is read-only, and nobody wrote the meta copy. The
    # duplicate button must say so rather than hand back an empty box.
    {"id": "agent-bare-9999", "name": "Bare Agent",
     "user_id": OTHER, "base_model_id": "gpt-4o-mini",
     "params": {"system": "Unreadable to anyone but the owner."},
     "meta": {"description": "bare", "toolIds": []},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 5, "updated_at": 5,
     "user": {"id": OTHER, "name": "Someone", "email": "other@example.com"}},
    {"id": "agent-hostile-e5f6", "name": HOSTILE_NAME,
     "user_id": OTHER, "base_model_id": "gpt-4o-mini",
     "params": {"system": HOSTILE_NAME},
     "meta": {"description": "hostile", "toolIds": []},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 4, "updated_at": 4,
     "user": {"id": OTHER, "name": "Someone", "email": "other@example.com"}},
]


def _models_list_envelope(rows):
    """What GET /api/v1/models/list sends: paged items plus the full count.

    /list only returns models that have a base_model_id, so the base models
    are not in it. That is why the page still needs /api/models as well.

    It also BLANKS params for any row the caller cannot write. Modelling that
    here is the whole reason the duplicate fallback can be tested: without it
    the stub would hand back instructions the real server never sends, and
    "Duplicate to my own" would look like it worked while copying nothing.
    """
    items = []
    for r in rows:
        if not r.get("base_model_id"):
            continue
        row = dict(r)
        if not row.get("write_access"):
            row["params"] = {}
        items.append(row)
    return {"items": items, "total": len(items)}


def _api_models_envelope(rows):
    """What GET /api/models sends: the row nested under `info`, with `params`
    deleted server side.

    Neither user_id nor params.system exists at the top level here, which is
    exactly the shape the page used to read and why every agent landed in the
    wrong bucket with a blank preview while all five tests passed.
    """
    out = []
    for row in rows:
        info = {k: v for k, v in row.items() if k != "params"}
        out.append({"id": row["id"], "name": row["name"], "object": "model",
                    "created": row.get("created_at", 0), "owned_by": "openai",
                    "preset": True, "connection_type": None,
                    "actions": [], "filters": [], "tags": [], "info": info})
    return {"data": out}


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
def page(browser, tmp_path):
    shutil.copy(STATIC / "agents.html", tmp_path / "agents.html")

    # Served over HTTP rather than opened as a file. Chromium's Fetch API
    # refuses a file:// URL outright, so on a file:// page the page's own
    # /api/... calls never reach page.route and the list renders empty no
    # matter what the stub was told to answer.
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
        # Page infrastructure, not something the user did. These are answered
        # but deliberately NOT recorded in `sent`, because several tests below
        # assert `sent == []` to prove a form did not submit, and every page
        # load calls both of these.
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/tools" in url:
            body = {"tools": [
                {"id": t, "label": t, "connected": True, "connect_url": ""}
                for t in ("gmail", "calendar", "gdrive", "documents",
                          "excel_creator", "executive_dashboard", "remember")
            ]}
        elif "/api/v1/models/list" in url:
            body = _models_list_envelope(MODELS)
        elif "/api/models" in url or url.rstrip("/").endswith("/api/v1/models"):
            body = _api_models_envelope(MODELS)
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


def test_your_own_agent_is_listed(page):
    assert page.locator('[data-agent-id="agent-mine-a1b2"]').count() == 1


def test_the_base_model_is_not_listed_as_an_agent(page):
    """gpt-4o-mini is a model, not an agent. Only ids we minted are agents."""
    assert page.locator('[data-agent-id="gpt-4o-mini"]').count() == 0


def test_someone_elses_agent_is_not_in_your_list(page):
    mine = page.locator("#my-agents [data-agent-id]").all()
    assert all("shared" not in (el.get_attribute("data-agent-id") or "")
               for el in mine)


def test_a_platform_agent_appears_in_its_own_group(page):
    assert page.locator('#platform-agents [data-agent-id="agent-shared-c3d4"]').count() == 1


def test_a_platform_agent_offers_no_delete(page):
    card = page.locator('#platform-agents [data-agent-id="agent-shared-c3d4"]')
    assert card.locator('[data-act="delete"]').count() == 0


def test_a_card_shows_the_agent_it_stands_for(page):
    """The partition being right says nothing about the card being right: a
    card whose title and instructions never render passes every other test
    in this file."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert card.locator(".card-title").inner_text() == "Researcher"
    assert "You research things carefully." in card.locator(".card-sys").inner_text()
    assert [e.get_attribute("data-agent-id")
            for e in page.locator("#my-agents [data-agent-id]").all()] == [
        "agent-mine-a1b2", "agent-mine-second-c5d6"]


def test_a_hostile_agent_name_is_shown_as_text_not_run(page):
    """The card is built with innerHTML, so the only thing between a name
    somebody else chose and script running in your session is esc()."""
    card = page.locator('[data-agent-id="agent-hostile-e5f6"]')
    title = card.locator(".card-title")
    assert not page.evaluate("window.__pwned"), "the name executed"
    assert title.inner_text() == HOSTILE_NAME
    assert title.locator("img").count() == 0
    assert card.locator(".card-sys").locator("img").count() == 0


# --- creating one ---------------------------------------------------------

# What the server really sends when an id is taken. Measured on production: it
# is a 401 with this detail, not a 400 and not a 409, so a retry that keys on
# the status code alone never fires.
DUPLICATE_ID_BODY = json.dumps({"detail": "Uh-oh! This model id is already "
                                "registered. Please choose another model id "
                                "string."})


def _open_form(page):
    page.locator("#new-agent").click()
    page.wait_for_selector("#agent-form", state="visible")


def _fill(page, name="Researcher", instructions="Research carefully."):
    _open_form(page)
    page.fill("#agent-name", name)
    page.fill("#agent-instructions", instructions)


def test_the_form_refuses_an_empty_name(page):
    _fill(page, name="", instructions="Something.")
    page.locator("#agent-save").click()
    assert page.locator("#form-error").inner_text().strip() != ""
    assert page.sent == [], "it sent a request despite an invalid form"


def test_the_form_refuses_empty_instructions(page):
    _fill(page, name="Researcher", instructions="")
    page.locator("#agent-save").click()
    assert page.locator("#form-error").inner_text().strip() != ""
    assert page.sent == []


def test_instructions_over_the_limit_are_refused_in_the_form(page):
    _fill(page, instructions="x" * 4001)
    page.locator("#agent-save").click()
    assert "4000" in page.locator("#form-error").inner_text()
    assert page.sent == []


def test_a_saved_agent_sends_the_instructions_as_params_system(page):
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    body = json.loads(page.sent[-1]["body"])
    assert body["params"]["system"] == "Research carefully."
    assert body["name"] == "Researcher"
    assert body["id"].startswith("agent-researcher-")


def test_the_connected_apps_switch_adds_the_proxy_tool(page):
    _fill(page)
    page.check("#use-my-apps")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["toolIds"] == ["server:mcp-proxy"]


def test_leaving_the_switch_off_sends_no_tools(page):
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["toolIds"] == []


@pytest.mark.parametrize("tool_id", [
    "gmail", "calendar", "gdrive", "documents", "excel_creator",
    "executive_dashboard", "remember"])
def test_each_native_tool_adds_only_itself(page, tool_id):
    _fill(page)
    page.check("#tool-" + tool_id)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["toolIds"] == [tool_id]


def test_an_id_collision_is_retried_once_with_a_new_suffix(page):
    """The id is a primary key across every model on the platform, and four hex
    characters can collide. The server reports the collision as a 401 carrying
    that detail, not as a 400 or a 409, so the stub sends the real thing."""
    seen = []

    def once(route):
        seen.append(route.request.post_data)
        if len(seen) == 1:
            route.fulfill(status=401, content_type="application/json",
                          body=DUPLICATE_ID_BODY)
        else:
            route.fulfill(status=200, content_type="application/json",
                          body='{"ok": true}')

    page.route("**/api/v1/models/create", once)
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(500)
    assert len(seen) == 2, "it gave up instead of retrying"
    assert json.loads(seen[0])["id"] != json.loads(seen[1])["id"]
    assert page.locator("#form-error").inner_text().strip() == ""


def test_a_real_401_is_not_mistaken_for_a_collision(page):
    """A genuine permission failure must not be retried forever, and must say
    something a user can act on rather than the duplicate-id message."""
    seen = []

    def denied(route):
        seen.append(route.request.post_data)
        route.fulfill(status=401, content_type="application/json",
                      body=json.dumps({"detail": "401 Unauthorized"}))

    page.route("**/api/v1/models/create", denied)
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(500)
    assert len(seen) == 1, "a plain 401 was retried as if the id were taken"
    assert page.locator("#form-error").inner_text().strip() != ""


def test_a_failed_save_keeps_what_the_user_typed(page):
    """Losing four paragraphs of instructions to a network blip is the worst
    thing this page can do."""
    _fill(page, instructions="Something I spent time on.")
    page.route("**/api/v1/models/create", lambda r: r.abort())
    page.locator("#agent-save").click()
    page.wait_for_timeout(400)
    assert page.input_value("#agent-instructions") == "Something I spent time on."
    assert page.locator("#form-error").inner_text().strip() != ""


def test_saving_closes_the_form_and_a_failure_leaves_it_open(page):
    """The form staying open on failure is what keeps the typed instructions
    reachable, so it is worth asserting rather than assuming."""
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert page.locator("#agent-form").is_visible() is False

    page.route("**/api/v1/models/create", lambda r: r.abort())
    _fill(page, instructions="Kept text.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(400)
    assert page.locator("#agent-form").is_visible() is True


# --- editing, deleting, duplicating ---------------------------------------


def test_edit_loads_the_existing_instructions(page):
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.input_value("#agent-instructions") == "You research things carefully."
    assert page.input_value("#agent-name") == "Researcher"


def test_edit_keeps_the_same_id(page):
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.fill("#agent-instructions", "Changed.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    sent = page.sent[-1]
    assert "agent-mine-a1b2" in sent["url"], "edit did not target the existing agent"
    assert json.loads(sent["body"])["id"] == "agent-mine-a1b2"


def test_delete_asks_first(page):
    page.on("dialog", lambda d: d.dismiss())
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="more"]').click()
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="delete"]').click()
    page.wait_for_timeout(300)
    assert page.sent == [], "it deleted without asking"


def test_delete_sends_the_id(page):
    """The id goes in the query string as well as the body. That is the shape
    proved against the live API; a body-only delete was never verified, and a
    stub would accept either."""
    page.on("dialog", lambda d: d.accept())
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="more"]').click()
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="delete"]').click()
    page.wait_for_timeout(300)
    sent = page.sent[-1]
    assert "/model/delete" in sent["url"]
    assert "agent-mine-a1b2" in sent["url"]
    assert json.loads(sent["body"]) == {"id": "agent-mine-a1b2"}


def test_deleting_one_agent_does_not_touch_another(page):
    page.on("dialog", lambda d: d.accept())
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="more"]').click()
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="delete"]').click()
    page.wait_for_timeout(300)
    assert "agent-shared-c3d4" not in page.sent[-1]["url"]


def test_duplicate_opens_a_new_agent_with_the_copied_instructions(page):
    """The copy comes from meta, because /list blanked params on this row: it
    is read-only to everyone except its owner. Reading params alone would hand
    the user an empty box on the one button that promises a copy."""
    page.locator('[data-agent-id="agent-shared-c3d4"] [data-act="duplicate"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.input_value("#agent-instructions") == "You summarise meetings."
    assert "Summariser" in page.input_value("#agent-name")


def test_duplicate_says_so_when_the_instructions_cannot_be_copied(page):
    """Never hand back a silently empty box on a button that promises a copy."""
    page.locator('[data-agent-id="agent-bare-9999"] [data-act="duplicate"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.input_value("#agent-instructions") == ""
    assert page.locator("#form-error").inner_text().strip() != ""


def test_duplicate_saves_as_a_new_agent_not_over_the_original(page):
    page.locator('[data-agent-id="agent-shared-c3d4"] [data-act="duplicate"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    sent = page.sent[-1]
    assert sent["url"].endswith("/create"), "duplicate edited the shared agent"
    assert json.loads(sent["body"])["id"] != "agent-shared-c3d4"


def test_duplicate_carries_the_tools_across(page):
    """A copy that silently loses the tools is not a copy."""
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="duplicate"]').count()
    # agent-mine-a1b2 is yours, so it offers Edit rather than Duplicate. Drive
    # the function directly for the tool-carrying case.
    page.evaluate(
        "() => window.__aiuiAgents.openForm("
        "  window.__aiuiAgents.state.agents.find(a => a.id === 'agent-mine-a1b2'))")
    page.wait_for_selector("#agent-form", state="visible")
    assert page.is_checked("#use-my-apps"), "the proxy tool was dropped"


def test_the_list_pages_until_it_has_everything(page):
    """/list returns at most 30 rows per page. Without paging, the thirty first
    agent onward simply vanish, with no error anywhere."""
    import urllib.parse

    many = [{"id": "agent-many-%02d" % i, "name": "Agent %02d" % i,
             "user_id": ME, "base_model_id": "gpt-4o-mini",
             "params": {"system": "Instructions %02d" % i},
             "meta": {"description": "many", "toolIds": []},
             "access_grants": [], "is_active": True, "write_access": True,
             "created_at": i, "updated_at": i,
             "user": {"id": ME, "name": "Me", "email": "me@example.com"}}
            for i in range(35)]

    def paged(route):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
        n = int((q.get("page") or ["1"])[0])
        chunk = many[(n - 1) * 30:n * 30]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"items": chunk, "total": len(many)}))

    page.route("**/api/v1/models/list*", paged)
    page.evaluate("() => window.__aiuiAgents.load()")
    page.wait_for_timeout(700)

    assert page.locator("#my-agents [data-agent-id]").count() == 35
    assert page.locator("#mine-count").inner_text() == "35"
    assert page.locator("#page-error").is_hidden()


def test_delete_targets_the_agent_whose_button_was_clicked(page):
    """With one owned agent, "delete the clicked agent" and "delete the first
    agent" look identical. This deletes the SECOND one."""
    page.on("dialog", lambda d: d.accept())
    page.locator('[data-agent-id="agent-mine-second-c5d6"] [data-act="more"]').click()
    page.locator('[data-agent-id="agent-mine-second-c5d6"] [data-act="delete"]').click()
    page.wait_for_timeout(300)
    sent = page.sent[-1]
    assert json.loads(sent["body"]) == {"id": "agent-mine-second-c5d6"}
    assert "agent-mine-a1b2" not in sent["url"]


def test_the_confirm_names_the_agent_being_deleted(page):
    """A confirm naming the wrong agent is worse than none: it invites a yes."""
    seen = []
    page.on("dialog", lambda d: (seen.append(d.message), d.dismiss()))
    page.locator('[data-agent-id="agent-mine-second-c5d6"] [data-act="more"]').click()
    page.locator('[data-agent-id="agent-mine-second-c5d6"] [data-act="delete"]').click()
    page.wait_for_timeout(300)
    assert seen and "Secondagent" in seen[0]


def test_editing_then_creating_does_not_overwrite_the_edited_agent(page):
    """editingId is shared across both paths. If it survives a cancelled edit,
    the next new agent silently updates the one that was open."""
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-cancel").click()

    _fill(page, name="Brandnew", instructions="Fresh instructions.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    sent = page.sent[-1]
    assert sent["url"].endswith("/create"), "it updated the agent that was open"
    assert json.loads(sent["body"])["id"] != "agent-mine-a1b2"


def test_a_save_always_sends_a_base_model(page):
    """A row with no base model is dropped by the list endpoint, so the agent
    would exist and never be shown again."""
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["base_model_id"] == "gpt-4o-mini"


def test_the_form_refuses_to_save_with_no_model_to_pick(page):
    """If every base model has vanished from the account, refuse rather than
    post an empty base_model_id and lose the agent."""
    _open_form(page)
    # Clear it AFTER opening: openForm repopulates the dropdown every time.
    page.evaluate("() => { document.getElementById('agent-base').innerHTML = ''; }")
    page.fill("#agent-name", "Nomodel")
    page.fill("#agent-instructions", "Something.")
    before = len(page.sent)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert len(page.sent) == before, "it saved with no base model"
    assert page.locator("#form-error").inner_text().strip() != ""


def test_a_save_keeps_the_readable_copy_of_the_instructions(page):
    """The ready-made agents are owned by an admin, who can edit them here. If
    a save dropped meta.agent_instructions, every other user would lose both
    the card preview and the duplicate button on them."""
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    meta = json.loads(page.sent[-1]["body"])["meta"]
    assert meta["agent_instructions"] == "Research carefully."


def test_duplicate_keeps_the_source_base_model(page):
    """openForm(null) leaves the dropdown on whichever model is first, which on
    this platform can be a pipe that cannot call tools at all."""
    page.evaluate("""() => {
      var sel = document.getElementById('agent-base');
      var o = document.createElement('option');
      o.value = 'zzz-other-model'; o.textContent = 'Other';
      sel.insertBefore(o, sel.firstChild);
    }""")
    page.locator('[data-agent-id="agent-shared-c3d4"] [data-act="duplicate"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["base_model_id"] == "gpt-4o-mini"


def test_a_stale_error_banner_does_not_survive_a_good_reload(page):
    page.evaluate("""() => {
      var el = document.getElementById('page-error');
      el.textContent = 'Could not load your agents.';
      el.hidden = false;
    }""")
    page.evaluate("() => window.__aiuiAgents.load()")
    page.wait_for_timeout(500)
    assert page.locator("#page-error").is_hidden()


# --- the page as somebody actually looks at it ----------------------------


def test_a_long_instruction_is_not_cut_mid_word(page):
    """The first version sliced at a fixed 180 characters and then line
    clamped on top, so real cards ended "Say plainly when you could not f"."""
    text = page.locator(
        '#my-agents [data-agent-id="agent-mine-a1b2"] .card-sys').inner_text()
    assert text, "the preview is empty"
    tail = text.rstrip().rstrip("\u2026").rstrip()
    assert not tail.endswith(" "), "trailing space before the ellipsis"
    # Whatever survives must be whole words, so the last chunk has to appear in
    # the source as a complete word.
    source = "You research things carefully."
    assert tail.split()[-1] in source.split() or tail in source


def test_a_shared_agent_is_marked_and_a_private_one_is_not(page):
    """Somebody looking at this page cannot otherwise tell which agents every
    other user can also see."""
    shared = page.locator('[data-agent-id="agent-shared-c3d4"] .tag')
    mine = page.locator('[data-agent-id="agent-mine-a1b2"] .tag')
    assert shared.count() == 1
    assert "everyone" in shared.inner_text().lower()
    assert mine.count() == 0, "a private agent was labelled as shared"


def test_the_card_says_what_the_agent_can_reach(page):
    """Tools are the whole point of an agent, and the card showed none."""
    chips = page.locator(
        '#my-agents [data-agent-id="agent-mine-a1b2"] .chip').all_inner_texts()
    assert "Your connected apps" in chips, chips


def test_an_agent_with_no_tools_says_so(page):
    chips = page.locator(
        '[data-agent-id="agent-shared-c3d4"] .chip').all_inner_texts()
    assert chips == ["No tools"], chips


def test_search_narrows_the_list(page):
    page.fill("#agent-search", "research")
    page.wait_for_timeout(200)
    ids = [e.get_attribute("data-agent-id")
           for e in page.locator("#my-agents [data-agent-id]").all()]
    assert ids == ["agent-mine-a1b2"], ids


def test_search_matches_the_instructions_too(page):
    """People remember what an agent does long before they remember its name."""
    page.fill("#agent-search", "research things carefully")
    page.wait_for_timeout(200)
    assert page.locator(
        '#my-agents [data-agent-id="agent-mine-a1b2"]').count() == 1


def test_a_search_with_no_hits_does_not_claim_you_have_no_agents(page):
    """Telling somebody they have no agents when they have twenty is how you
    get a duplicate created."""
    page.fill("#agent-search", "zzzz-nothing-matches")
    page.wait_for_timeout(200)
    assert page.locator("#no-match").is_visible()
    assert page.locator("#mine-empty").is_hidden()
    assert page.locator("#mine-count").inner_text() == "2"


def test_clearing_the_search_brings_everything_back(page):
    page.fill("#agent-search", "zzzz")
    page.wait_for_timeout(200)
    page.fill("#agent-search", "")
    page.wait_for_timeout(200)
    assert page.locator("#my-agents [data-agent-id]").count() == 2
    assert page.locator("#no-match").is_hidden()


def test_the_hostile_name_cannot_escape_through_the_avatar(page):
    """The avatar is built from the name, so it is a second interpolation of
    attacker controlled text into innerHTML."""
    card = page.locator('[data-agent-id="agent-hostile-e5f6"]')
    assert not page.evaluate("window.__pwned")
    assert card.locator(".avatar img").count() == 0


def test_an_edit_sends_access_grants_so_the_save_does_not_500(page):
    """The update endpoint revalidates the payload and requires this to be a
    list. Leaving it out sends null, fails validation, and comes back as a bare
    500, which is why editing an agent did not work at all."""
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.fill("#agent-instructions", "Changed.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    body = json.loads(page.sent[-1]["body"])
    assert isinstance(body.get("access_grants"), list), body


def test_editing_a_shared_agent_keeps_it_shared(page):
    """An empty list is what makes an agent private. Resetting it on save
    would quietly unshare a ready made agent from everybody, and its owner is
    the only person who can do that damage."""
    page.evaluate("""() => {
      var a = window.__aiuiAgents.state.agents.find(x => x.id === 'agent-mine-a1b2');
      a.access_grants = [{principal_type: 'user', principal_id: '*',
                          permission: 'read'}];
      window.__aiuiAgents.render();
    }""")
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.fill("#agent-instructions", "Changed.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    grants = json.loads(page.sent[-1]["body"])["access_grants"]
    assert any(g.get("principal_id") == "*" for g in grants), grants


def test_a_new_agent_is_created_with_no_grants(page):
    """No grant is what private means."""
    _fill(page)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["access_grants"] == []


@pytest.mark.parametrize("bad", ["Research Agent", "my agent", "a", "1jack",
                                 "jack!", "way-too-long-a-name-for-an-agent"])
def test_a_name_that_cannot_be_said_in_a_sentence_is_refused(page, bad):
    """The name is how you reach the agent in a chat, so it has to be one
    plain word."""
    _open_form(page)
    page.fill("#agent-name", bad)
    page.fill("#agent-instructions", "Something.")
    before = len(page.sent)
    page.locator("#agent-save").click()
    page.wait_for_timeout(250)
    assert len(page.sent) == before, "it saved a name you cannot say"
    assert page.locator("#form-error").inner_text().strip() != ""


def test_duplicate_suggests_a_name_that_can_be_saved(page):
    """"Scout (my copy)" would be rejected the moment they pressed save, on a
    name they never typed."""
    page.locator('[data-agent-id="agent-shared-c3d4"] [data-act="duplicate"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    suggested = page.input_value("#agent-name")
    assert " " not in suggested, suggested
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert page.locator("#form-error").inner_text().strip() == ""


# --- the wait ---------------------------------------------------------------


def test_the_skeleton_is_gone_once_the_agents_are_in(page):
    """It stands in for the cards while two round trips and a paged list are
    in flight. Leaving it up afterwards would be worse than never showing it."""
    assert page.locator("#agents-skeleton").is_hidden()
    assert page.locator("#my-agents [data-agent-id]").count() > 0


def test_the_skeleton_is_hidden_even_when_the_load_fails(page):
    """A failed load must not leave the page shimmering forever underneath an
    error message. This is why it is hidden in a finally, not after render."""
    page.route("**/api/v1/models/list*", lambda r: r.abort())
    page.evaluate("() => { document.getElementById('agents-skeleton').hidden = false; }")
    page.evaluate("() => window.__aiuiAgents.load()")
    page.wait_for_timeout(500)

    assert page.locator("#agents-skeleton").is_hidden()
    assert page.locator("#page-error").is_visible()


def test_the_skeleton_is_in_the_markup_not_drawn_by_script(page):
    """It has to be on screen before any script runs, which is the whole point:
    the wait it covers starts before the first fetch."""
    import re as _re
    html = pathlib.Path(STATIC / "agents.html").read_text(encoding="utf-8")
    assert 'id="agents-skeleton"' in html
    assert html.count("skeleton sk-avatar") >= 3, "expected several placeholder cards"


def test_the_shimmer_stops_for_reduced_motion(page):
    """An animation that never stops is exactly what that setting is for."""
    html = pathlib.Path(STATIC / "agents.html").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in html
