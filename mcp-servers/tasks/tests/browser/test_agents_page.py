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

# A name that runs script if the page ever stops escaping. Owned by ME: the
# page no longer lists anything belonging to anyone else, and an agent that is
# never rendered cannot prove the name was escaped.
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
    # The free-model router. Selectable, and the reason Ada failed 409 times
    # in forty hours, so the form has to say something about it.
    {"id": "auto_router.auto", "name": "Auto (Free)", "user_id": None,
     "base_model_id": None, "params": {}, "meta": {},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 7, "updated_at": 7, "user": None},
    {"id": "agent-mine-a1b2", "name": "Researcher",
     "user_id": ME, "base_model_id": "gpt-4o-mini",
     "params": {"system": "You research things carefully."},
     "meta": {"description": "mine", "toolIds": ["server:mcp-proxy"],
              "role": "Project manager", "skillIds": ["daily-standup"]},
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
              "role": "Meeting notes",
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
     "user_id": ME, "base_model_id": "gpt-4o-mini",
     "params": {"system": HOSTILE_NAME},
     # A hostile ROLE as well as a hostile name: the role is free text the
     # owner types, and it goes through the same innerHTML as the name.
     "meta": {"description": "hostile", "toolIds": [], "role": HOSTILE_NAME},
     "access_grants": [], "is_active": True, "write_access": False,
     "created_at": 4, "updated_at": 4,
     "user": {"id": ME, "name": "Me", "email": "me@example.com"}},
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
        elif "/agents/activity" in url:
            body = {"activity": {}}
        elif "/agents/seed" in url:
            body = {"seeded": False, "created": 0}
        elif "/agents/skills" in url:
            body = {"skills": SKILLS}
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


def test_a_card_shows_the_agent_it_stands_for(page):
    """The partition being right says nothing about the card being right: a
    card whose title and instructions never render passes every other test
    in this file."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert card.locator(".card-title").inner_text() == "Researcher"
    assert "You research things carefully." in card.locator(".card-sys").inner_text()
    assert [e.get_attribute("data-agent-id")
            for e in page.locator("#my-agents [data-agent-id]").all()] == [
        "agent-mine-a1b2", "agent-mine-second-c5d6", "agent-hostile-e5f6"]


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
    page.check("#use-my-apps")   # already on by default; explicit on purpose
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["toolIds"] == ["server:mcp-proxy"]


def test_turning_everything_off_and_picking_nothing_sends_no_tools(page):
    """The switch defaults to on now, so this has to turn it off first. An
    agent narrowed to nothing is somebody who has not finished choosing, and
    the server treats it as everything rather than as an agent that can do
    nothing at all."""
    _fill(page)
    page.uncheck("#use-my-apps")
    page.wait_for_timeout(100)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["toolIds"] == []


@pytest.mark.parametrize("tool_id", [
    "gmail", "calendar", "gdrive", "documents", "excel_creator",
    "executive_dashboard", "remember"])
def test_each_native_tool_adds_only_itself(page, tool_id):
    _fill(page)
    page.uncheck("#use-my-apps")
    page.wait_for_timeout(100)
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


def test_the_card_says_what_the_agent_can_reach(page):
    """Tools are the whole point of an agent, and the card showed none."""
    chips = page.locator(
        '#my-agents [data-agent-id="agent-mine-a1b2"] .chip').all_inner_texts()
    assert "Your connected apps" in chips, chips


def test_an_agent_with_no_tools_says_so(page):
    # agent-mine-second-c5d6 carries toolIds: []. It used to check a shared
    # agent, and nothing shared is listed any more.
    chips = page.locator(
        '[data-agent-id="agent-mine-second-c5d6"] .chip').all_inner_texts()
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
    assert page.locator("#mine-count").inner_text() == "3"


def test_clearing_the_search_brings_everything_back(page):
    page.fill("#agent-search", "zzzz")
    page.wait_for_timeout(200)
    page.fill("#agent-search", "")
    page.wait_for_timeout(200)
    assert page.locator("#my-agents [data-agent-id]").count() == 3
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


# Removed with the Ready-made section: nothing is shared any more, so there is
# no group for other people's agents and nothing to duplicate into your own.
# The page lists only what you own, because Open WebUI hands an admin every
# user's models whatever their grants.
# Gone: test_a_platform_agent_appears_in_its_own_group, test_a_platform_agent_offers_no_delete, test_someone_elses_agent_is_not_in_your_list, test_a_shared_agent_is_marked_and_a_private_one_is_not, test_duplicate_opens_a_new_agent_with_the_copied_instructions, test_duplicate_says_so_when_the_instructions_cannot_be_copied, test_duplicate_saves_as_a_new_agent_not_over_the_original, test_duplicate_keeps_the_source_base_model, test_duplicate_suggests_a_name_that_can_be_saved


def test_someone_elses_agent_is_never_rendered(page):
    """Open WebUI hands an admin every model whatever its grants, so the
    listing this page receives can contain other people's private agents. It
    used to show them under Ready-made with a Duplicate button. Nothing that
    is not yours may appear anywhere on the page."""
    ids = [e.get_attribute("data-agent-id")
           for e in page.locator("[data-agent-id]").all()]
    assert "agent-shared-c3d4" not in ids, ids
    assert "agent-private-other" not in ids, ids
    assert all(i and i.startswith(("agent-mine", "agent-hostile")) for i in ids), ids


# --- is the agent awake, and how long did it take -------------------------

def _activity(page, payload):
    """Re-answer the activity route, then make the page ask again."""
    page.route("**/api/tasks/agents/activity", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"activity": payload})))
    page.evaluate("() => window.__aiuiAgents.render()")
    page.wait_for_timeout(400)


def test_a_working_agent_says_so_with_its_elapsed_time(page):
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "working", "running_for_seconds": 14,
        "last_run_at": "2026-08-28T12:00:00+00:00", "source": "schedule"}})
    line = page.locator('[data-activity-for="agent-mine-a1b2"]')
    assert "Working" in line.inner_text()
    assert "14s" in line.inner_text()


def test_an_idle_agent_says_when_it_was_used_and_how_long_it_took(page):
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "idle", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 8, "source": "schedule"}})
    text = page.locator('[data-activity-for="agent-mine-a1b2"]').inner_text()
    assert "Idle" in text
    assert "took 8s" in text


def test_an_agent_that_has_never_run_says_nothing(page):
    """Calling something idle when it has never done anything reads as a
    status. Saying nothing reads as new, which is what it is."""
    page = page
    _activity(page, {})
    assert page.locator(
        '[data-activity-for="agent-mine-a1b2"]').inner_text().strip() == ""


def test_a_failed_run_is_not_dressed_up_as_idle(page):
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "idle", "last_status": "failed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 3, "source": "channel"}})
    assert "Failed" in page.locator(
        '[data-activity-for="agent-mine-a1b2"]').inner_text()


def _dot_state(page):
    """The class the activity line is wearing, which is what colours the dot."""
    return page.locator(
        '[data-activity-for="agent-mine-a1b2"]').get_attribute("class")


def test_the_dot_is_green_while_a_run_is_in_flight(page):
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "working", "running_for_seconds": 5,
        "last_run_at": "2026-08-28T12:00:00+00:00", "source": "schedule"}})
    assert "working" in _dot_state(page)


def test_the_dot_is_amber_when_the_agent_is_resting(page):
    """Grey read as "switched off" for an agent that is simply between runs
    and perfectly healthy."""
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "idle", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 8, "source": "schedule"}})
    assert "idle" in _dot_state(page)
    assert "blocked" not in _dot_state(page)


def test_the_dot_is_red_after_a_failure(page):
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "idle", "last_status": "failed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 3, "source": "channel"}})
    assert "blocked" in _dot_state(page)


def test_an_agent_stopped_for_approval_reads_as_blocked_not_idle(page):
    """It ended asking permission, so it is stuck on a person. Calling that
    idle hides the one state the owner has to act on."""
    page = page
    _activity(page, {"agent-mine-a1b2": {
        "state": "idle", "last_status": "waiting",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    text = page.locator('[data-activity-for="agent-mine-a1b2"]').inner_text()
    assert "Needs approval" in text
    assert "Idle" not in text
    assert "blocked" in _dot_state(page)


def test_an_agent_that_never_ran_wears_no_state_colour(page):
    page = page
    _activity(page, {})
    klass = _dot_state(page)
    assert "idle" not in klass and "blocked" not in klass         and "working" not in klass


# --- the role -------------------------------------------------------------

# Ralph asked for this looking at his own two cards: a name and a model id
# tell you nothing about what an agent is for. The role is typed by the owner,
# shows under the name, and reaches the agent's brief.

def test_a_card_shows_the_role_under_the_name(page):
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert card.locator(".card-role").inner_text() == "Project manager"
    assert card.locator(".card-heading .card-model").count() == 0, (
        "the model id should give up the subtitle line to the role")


def test_the_model_is_still_on_the_card_when_a_role_took_its_line(page):
    """Demoted, not deleted. Which model an agent runs on is what you look at
    when one of them is being slow or stupid."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert "gpt-4o-mini" in card.inner_text()


def test_an_agent_with_no_role_still_shows_its_model(page):
    """Every agent that existed before this field has no role. Their cards
    must not lose a line, or the change looks like breakage."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-second-c5d6"]')
    assert card.locator(".card-role").count() == 0
    assert card.locator(".card-heading .card-model").inner_text() == "gpt-4o-mini"


def test_a_hostile_role_is_shown_as_text_not_run(page):
    card = page.locator('[data-agent-id="agent-hostile-e5f6"]')
    role = card.locator(".card-role")
    assert not page.evaluate("window.__pwned"), "the role executed"
    assert role.inner_text() == HOSTILE_NAME
    assert role.locator("img").count() == 0


def test_a_saved_agent_sends_its_role(page):
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.fill("#agent-role", "Project manager")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["role"] == "Project manager"


def test_leaving_the_role_blank_writes_no_role(page):
    """Optional means optional. An empty string stored as a role would read
    back as a role somebody chose, and the brief would interpolate nothing
    into a sentence built to hold something."""
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert "role" not in json.loads(page.sent[-1]["body"])["meta"]


def test_clearing_the_role_on_an_edit_removes_it(page):
    _open = page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]')
    _open.click()
    page.wait_for_selector("#agent-form", state="visible")
    page.fill("#agent-role", "")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert "role" not in json.loads(page.sent[-1]["body"])["meta"]


def test_edit_loads_the_existing_role(page):
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.input_value("#agent-role") == "Project manager"


def test_a_new_form_does_not_inherit_the_last_agents_role(page):
    """openForm fills every field from the agent or blanks it. A field added
    to the form and forgotten here carries the previous agent's value into a
    new one, which is how the access radios broke once already."""
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-cancel").click()
    _open_form(page)
    assert page.input_value("#agent-role") == ""


def test_the_role_field_caps_what_can_be_typed(page):
    _open_form(page)
    assert page.get_attribute("#agent-role", "maxlength") == "32"


def test_duplicating_an_agent_carries_its_role(page):
    """A copy of a project manager is a project manager. Every other field on
    this form is carried across; a role left behind would be the one thing
    silently lost."""
    # Driven directly, the same way test_duplicate_carries_the_tools_across
    # does: the page lists only your own agents now, so the Duplicate button
    # has no card to sit on.
    page.evaluate(
        "() => window.__aiuiAgents.duplicate("
        "  window.__aiuiAgents.state.agents.find("
        "    a => a.id === 'agent-shared-c3d4'))")
    page.wait_for_selector("#agent-form", state="visible")
    assert page.input_value("#agent-role") == "Meeting notes"


def test_search_finds_an_agent_by_its_role(page):
    """The role is now the most human thing on the card, so it is the word
    somebody will type when they cannot remember which one is which."""
    page.fill("#agent-search", "project manager")
    page.wait_for_timeout(200)
    shown = [e.get_attribute("data-agent-id")
             for e in page.locator("#my-agents [data-agent-id]").all()]
    assert shown == ["agent-mine-a1b2"]


# --- awake ----------------------------------------------------------------

# Ralph, watching a card say Idle a second after Ada answered him: "they idle
# even though its not 10minutes yet". Awake is the state between working and
# resting, and it is what somebody looking at the card actually wants.

def test_a_recently_used_agent_reads_as_awake(page):
    _activity(page, {"agent-mine-a1b2": {
        "state": "awake", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    text = page.locator('[data-activity-for="agent-mine-a1b2"]').inner_text()
    assert "Awake" in text
    assert "Idle" not in text
    assert "took 2s" in text


def test_the_dot_is_green_when_the_agent_is_awake(page):
    """Green like Working, because both mean the agent is with you. The pulse
    is what separates them: Working is thinking right now."""
    _activity(page, {"agent-mine-a1b2": {
        "state": "awake", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    klass = _dot_state(page)
    assert "awake" in klass
    assert "idle" not in klass and "blocked" not in klass


def test_awake_is_still_green_but_does_not_pulse(page):
    """The pulse is reserved for a run in flight. An agent that pulsed for ten
    minutes after every answer would make the one signal that means "it is
    thinking right now" mean nothing."""
    _activity(page, {"agent-mine-a1b2": {
        "state": "awake", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    dot = page.locator('[data-activity-for="agent-mine-a1b2"] .dot')
    colour = dot.evaluate("el => getComputedStyle(el).backgroundColor")
    animation = dot.evaluate("el => getComputedStyle(el).animationName")
    assert colour == "rgb(74, 222, 128)", colour
    assert animation == "none", animation


# --- the edit form is two columns on a wide screen -------------------------

# Ralph asked for a wider modal to make room for a list of skills. Width on
# its own is not the point: one column of fields in a 980px box just makes the
# eye travel further, so the fields reflow into two.

def _box(page, sel):
    return page.locator(sel).bounding_box()


def test_the_agent_form_is_wider_than_the_other_dialogs(page):
    """Scoped to this one form. .modal is shared with Connections and the
    clear-confirm dialog, and widening those would be a regression nobody
    asked for."""
    _open_form(page)
    form = _box(page, "#agent-form")
    assert form["width"] > 800, form["width"]
    page.locator("#agent-cancel").click()
    page.locator("#open-connections").click()
    page.wait_for_selector("#connections-panel", state="visible")
    assert _box(page, "#connections-panel")["width"] < 700


def test_the_settings_sit_beside_the_instructions_not_below_them(page):
    """Two columns: who the agent is on the left, what it can do on the right.
    Checked by geometry rather than by class name, because a grid that never
    applied would still carry the class."""
    _open_form(page)
    name = _box(page, "#agent-name")
    model = _box(page, "#agent-base")
    assert model["x"] > name["x"] + name["width"] - 1, (
        "the model field is not in a second column")
    assert model["y"] < name["y"] + 200, (
        "the second column starts far below the first, so it is not beside it")


def test_a_narrow_window_puts_it_back_to_one_column(page):
    """A phone gets the single column it had. Two 440px columns do not fit and
    would either overflow the screen or shrink both fields to nothing."""
    page.set_viewport_size({"width": 700, "height": 1000})
    _open_form(page)
    name = _box(page, "#agent-name")
    model = _box(page, "#agent-base")
    assert model["y"] > name["y"], "the fields did not stack"
    assert abs(model["x"] - name["x"]) < 2, "they are still side by side"
    page.set_viewport_size({"width": 1500, "height": 1000})


def test_every_field_is_still_reachable_after_the_reflow(page):
    """The reflow moves markup. A field that ended up outside the form, or
    hidden behind the grid, would break saving without breaking anything a
    layout test looks at."""
    _open_form(page)
    for sel in ("#agent-name", "#agent-role", "#agent-instructions",
                "#agent-base", "#use-my-apps", "#native-tools",
                "#agent-save", "#agent-cancel"):
        assert page.locator("#agent-form " + sel).count() == 1, sel
    assert page.locator("#agent-form input[name='agent-access']").count() == 3


# --- skills ---------------------------------------------------------------

# A skill is ready-made instructions for one job. The list sits full width
# under the two columns, because a skill is only pickable when its name and
# what it does fit on one line.

SKILLS = [
    {"name": "inbox-triage", "tools": ["gmail"], "tags": ["email", "triage"],
     "description": "Sort unread mail into what needs a reply today. Use when "
                    "asked about email."},
    {"name": "daily-standup", "tools": ["server:mcp-proxy"],
     "tags": ["planning", "reporting"],
     "description": "What moved, what is stuck, what is due. Use when asked "
                    "for a standup."},
    {"name": "write-a-document", "tools": ["documents"],
     "tags": ["documents", "writing"],
     "description": "Produce a real Word or PDF file. Use when asked for a "
                    "report or a letter."},
]


def test_the_form_lists_every_skill_the_server_offers(page):
    """Names only. What each one does is one click away and is covered by the
    browsing tests further down; this one is about the list existing and
    being complete, which is what a failed fetch would break."""
    _open_form(page)
    block = page.locator("#agent-skills")
    assert block.count() == 1, "there is no skills list on the form"
    shown = [e.get_attribute("data-skill")
             for e in page.locator("#agent-skills .skill").all()]
    assert shown == [s["name"] for s in SKILLS], shown


def test_ticking_a_skill_saves_it_on_the_agent(page):
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.check("#skill-inbox-triage")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["skillIds"] == ["inbox-triage"]


def test_an_agent_with_no_skills_writes_no_skill_list(page):
    """Same rule as the role and the access level: an agent with none must
    look exactly as it did before this existed."""
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert "skillIds" not in json.loads(page.sent[-1]["body"])["meta"]


def test_edit_shows_which_skills_the_agent_already_has(page):
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    assert page.is_checked("#skill-daily-standup")
    assert not page.is_checked("#skill-inbox-triage")


def test_a_new_form_does_not_inherit_the_last_agents_skills(page):
    page.locator('[data-agent-id="agent-mine-a1b2"] [data-act="edit"]').click()
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-cancel").click()
    _open_form(page)
    assert not page.is_checked("#skill-daily-standup")


def test_the_skills_sit_below_both_columns_not_inside_one(page):
    """Full width. Squeezed into half, a person would be choosing from names
    alone, which is the thing the description exists to prevent."""
    _open_form(page)
    skills = _box(page, "#agent-skills")
    name = _box(page, "#agent-name")
    model = _box(page, "#agent-base")
    assert skills["y"] > name["y"], "the skills are above the fields"
    assert skills["width"] > (model["x"] + model["width"] - name["x"]) * 0.9, (
        "the skills list is not full width")


def test_the_card_shows_the_skills_an_agent_has(page):
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert "daily-standup" in card.inner_text()


# --- browsing the skills --------------------------------------------------

# Ralph, after seeing the marketplace: "name only and then if they click it
# will show the description". Ten names fit on a screen where ten
# descriptions do not, and the list has to still work at a hundred.

def _skill_row(page, name):
    return page.locator('[data-skill="%s"]' % name)


def test_a_row_shows_the_name_not_the_description(page):
    _open_form(page)
    row = _skill_row(page, "inbox-triage")
    assert "inbox-triage" in row.inner_text()
    assert not row.locator(".skill-what").is_visible(), (
        "the description is open before anybody asked for it")


def test_clicking_the_name_shows_what_it_does(page):
    _open_form(page)
    row = _skill_row(page, "inbox-triage")
    row.locator(".skill-open").click()
    assert row.locator(".skill-what").is_visible()
    assert "Sort unread mail" in row.inner_text()
    assert "Gmail" in row.inner_text(), "it does not say which tool it needs"


def test_reading_a_skill_does_not_give_it_to_the_agent(page):
    """The one thing this layout must never do. Two targets on one row, and
    the wrong one silently changing an agent's behaviour would be worse than
    the wall of text it replaced."""
    _open_form(page)
    _skill_row(page, "inbox-triage").locator(".skill-open").click()
    assert not page.is_checked("#skill-inbox-triage")


def test_ticking_a_skill_does_not_open_it(page):
    _open_form(page)
    page.check("#skill-inbox-triage")
    assert not _skill_row(page, "inbox-triage").locator(
        ".skill-what").is_visible()


def test_only_one_skill_is_open_at_a_time(page):
    """Otherwise reading four of them rebuilds the wall of text this replaced."""
    _open_form(page)
    _skill_row(page, "inbox-triage").locator(".skill-open").click()
    _skill_row(page, "daily-standup").locator(".skill-open").click()
    assert _skill_row(page, "daily-standup").locator(".skill-what").is_visible()
    assert not _skill_row(page, "inbox-triage").locator(
        ".skill-what").is_visible()


def test_a_tag_filters_the_list(page):
    _open_form(page)
    page.locator('[data-tag="email"]').click()
    assert _skill_row(page, "inbox-triage").is_visible()
    assert not _skill_row(page, "daily-standup").is_visible()


def test_the_tag_says_how_many_it_has(page):
    _open_form(page)
    assert "1" in page.locator('[data-tag="email"]').inner_text()
    assert "3" in page.locator('[data-tag=""]').inner_text(), "no All count"


def test_searching_matches_name_description_and_tag(page):
    _open_form(page)
    for term, expected in [("triage", "inbox-triage"),
                           ("unread mail", "inbox-triage"),
                           ("reporting", "daily-standup")]:
        page.fill("#skill-search", term)
        page.wait_for_timeout(120)
        assert _skill_row(page, expected).is_visible(), term


def test_a_search_that_matches_nothing_says_so(page):
    _open_form(page)
    page.fill("#skill-search", "zzzznothing")
    page.wait_for_timeout(120)
    assert page.locator("#skill-none").is_visible()


def test_a_hidden_skill_is_still_saved(page):
    """Filtering is a view. A skill ticked and then filtered out of sight must
    not quietly come off the agent, which is exactly what reading the checked
    boxes out of the DOM would do if the row were removed rather than hidden."""
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.check("#skill-inbox-triage")
    page.fill("#skill-search", "standup")
    page.wait_for_timeout(120)
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["meta"]["skillIds"] == ["inbox-triage"]


def test_the_list_says_how_much_of_it_you_are_seeing(page):
    """With a scroller and a filter, nothing else tells you the library is
    bigger than the rows on screen."""
    _open_form(page)
    assert "3 skills" in page.locator("#skill-count").inner_text()
    page.fill("#skill-search", "triage")
    page.wait_for_timeout(150)
    assert "1 of 3" in page.locator("#skill-count").inner_text()


def test_the_count_says_how_many_are_chosen(page):
    _open_form(page)
    page.check("#skill-inbox-triage")
    page.wait_for_timeout(120)
    assert "1 chosen" in page.locator("#skill-count").inner_text()


# --- compact cards ---------------------------------------------------------

# The cap is 25 agents, and Ralph is right that agents building agents makes
# that reachable rather than theoretical. At the old height 25 cards was about
# 8,000 pixels of scrolling in a single column.

def test_a_card_is_short_enough_to_scan_a_screenful(page):
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    box = card.bounding_box()
    assert box["height"] < 240, box["height"]


def test_the_name_and_role_share_a_line(page):
    """The role is two or three words. Giving it a line of its own costs
    twenty pixels a card for nothing."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    name = card.locator(".card-title").bounding_box()
    role = card.locator(".card-role").bounding_box()
    assert role["x"] > name["x"] + name["width"] - 1, "the role is not beside the name"
    assert abs(role["y"] - name["y"]) < 8, "they are on different lines"


def test_skills_and_tools_share_one_row(page):
    """Two rows each with a minimum height, for an agent that usually has
    three chips in total."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    skill = card.locator(".chip.skill").first.bounding_box()
    tool = card.locator(".card-chips .chip:not(.skill):not(.model)").first.bounding_box()
    assert abs(skill["y"] - tool["y"]) < 30, (skill, tool)


def test_the_card_still_says_what_the_agent_is_for(page):
    """The one thing not worth compacting away. With ten agents this line is
    how you tell them apart, and a card of name plus chips makes you open
    every one to remember what it does."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    assert "You research things carefully" in card.locator(".card-sys").inner_text()


def test_everything_that_was_on_the_card_is_still_on_it(page):
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    text = card.inner_text()
    for want in ("Researcher", "Project manager", "daily-standup",
                 "gpt-4o-mini", "Edit"):
        assert want in text, want


def test_no_emoji_on_the_card(page):
    """Ralph asked for none. The tool glyphs are inline SVG and the skill
    chips are plain text, and this keeps it that way."""
    card = page.locator('#my-agents [data-agent-id="agent-mine-a1b2"]')
    text = card.inner_text()
    assert not any(ord(ch) > 0x2100 for ch in text), \
        [ch for ch in text if ord(ch) > 0x2100]


# --- warning about a model that cannot hold up --------------------------

# Ada failed 409 times in forty hours against Mia's 62, and every failing
# hour was an hour Ada was on Auto (Free). The dropdown offered it with
# nothing to say it is a shared free pool that runs out.

def test_choosing_the_free_router_warns_you(page):
    _open_form(page)
    page.select_option("#agent-base", "auto_router.auto")
    page.wait_for_timeout(120)
    warn = page.locator("#model-warn")
    assert warn.is_visible()
    text = warn.inner_text().lower()
    assert "free" in text
    assert "specific model" in text, "it does not say what to do instead"


def test_an_ordinary_model_warns_about_nothing(page):
    _open_form(page)
    page.select_option("#agent-base", "gpt-4o-mini")
    page.wait_for_timeout(120)
    assert not page.locator("#model-warn").is_visible()


def test_the_warning_clears_when_you_pick_something_else(page):
    _open_form(page)
    page.select_option("#agent-base", "auto_router.auto")
    page.wait_for_timeout(120)
    assert page.locator("#model-warn").is_visible()
    page.select_option("#agent-base", "gpt-4o-mini")
    page.wait_for_timeout(120)
    assert not page.locator("#model-warn").is_visible()


def test_the_warning_shows_on_opening_an_agent_already_on_it(page):
    """The case that matters most: somebody who already chose it and is
    wondering why their agent keeps failing."""
    page.evaluate(
        "() => { const a = window.__aiuiAgents.state.agents"
        ".find(x => x.id === 'agent-mine-a1b2');"
        " a.base_model_id = 'auto_router.auto';"
        " window.__aiuiAgents.openForm(a); }")
    page.wait_for_selector("#agent-form", state="visible")
    page.wait_for_timeout(120)
    assert page.locator("#model-warn").is_visible()


def test_the_free_router_is_still_choosable(page):
    """Warned about, not removed. Somebody running a cheap experiment is
    entitled to pick it, and taking the option away would be us deciding."""
    _open_form(page)
    page.select_option("#agent-base", "auto_router.auto")
    page.fill("#agent-name", "Cheap")
    page.fill("#agent-instructions", "Do a thing.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert json.loads(page.sent[-1]["body"])["base_model_id"] == "auto_router.auto"


# --- tools: everything, or only what you pick -------------------------------

# Measured on production: Mia had one tool ticked and reached twelve, because
# _resolve_agent added everything the owner could reach on top of whatever was
# ticked. The checkboxes implied a choice nobody was making. Ralph's words:
# "let this agent use my connected apps should be like connect to all apps,
# and then the apps below will hide; if not, it will show". He said yes to the
# narrow choice actually restricting.

def test_the_master_switch_is_on_and_the_list_is_hidden(page):
    _open_form(page)
    assert page.is_checked("#use-my-apps")
    assert not page.locator("#native-tools").is_visible(), (
        "the list is showing while the switch says everything")


def test_turning_it_off_shows_the_list(page):
    _open_form(page)
    page.uncheck("#use-my-apps")
    page.wait_for_timeout(120)
    assert page.locator("#native-tools").is_visible()


def test_everything_writes_no_scope(page):
    """Every agent that existed before this has none, so the default must
    write none: an unrelated edit cannot quietly narrow an agent."""
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    assert "toolScope" not in json.loads(page.sent[-1]["body"])["meta"]


def test_picking_writes_the_scope_and_the_tools(page):
    _fill(page, name="Researcher", instructions="Research carefully.")
    page.uncheck("#use-my-apps")
    page.wait_for_timeout(100)
    page.check("#tool-gmail")
    page.locator("#agent-save").click()
    page.wait_for_timeout(300)
    meta = json.loads(page.sent[-1]["body"])["meta"]
    assert meta["toolScope"] == "picked"
    assert "gmail" in meta["toolIds"]
    assert "server:mcp-proxy" not in meta["toolIds"]


def test_edit_shows_the_scope_the_agent_has(page):
    page.evaluate(
        "() => { const a = window.__aiuiAgents.state.agents"
        ".find(x => x.id === 'agent-mine-a1b2');"
        " a.meta.toolScope = 'picked';"
        " window.__aiuiAgents.openForm(a); }")
    page.wait_for_selector("#agent-form", state="visible")
    page.wait_for_timeout(120)
    assert not page.is_checked("#use-my-apps")
    assert page.locator("#native-tools").is_visible()


def test_a_new_form_goes_back_to_everything(page):
    page.evaluate(
        "() => { const a = window.__aiuiAgents.state.agents"
        ".find(x => x.id === 'agent-mine-a1b2');"
        " a.meta.toolScope = 'picked';"
        " window.__aiuiAgents.openForm(a); }")
    page.wait_for_selector("#agent-form", state="visible")
    page.locator("#agent-cancel").click()
    _open_form(page)
    assert page.is_checked("#use-my-apps")


def test_the_tool_list_scrolls_rather_than_growing(page):
    """Ralph asked for this directly: the list gets longer as tools are added
    and must not keep pushing the rest of the form down."""
    _open_form(page)
    page.uncheck("#use-my-apps")
    page.wait_for_timeout(120)
    overflow = page.locator("#native-tools").evaluate(
        "el => getComputedStyle(el).overflowY")
    assert overflow in ("auto", "scroll"), overflow
