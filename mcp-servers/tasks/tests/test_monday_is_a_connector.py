"""monday.com: boards and items, as you, with a personal API token.

The second GraphQL connector, after Linear, and three things about it were
read off monday's docs (2026-11-24) because each one fails silently:

**A refusal is HTTP 200 with `"data": []`.** Linear's is `"data": null`,
and the check written for Linear read monday's empty list as a success, so
a failed create would have reached the model as done. The connect check
had the same blind spot for every GraphQL vendor: it read only the status.

**column_values is a JSON STRING inside the JSON body**, keyed by column
id, not by the title a person sees.

**The API version is pinned.** Left out, monday answers with whatever is
Current that month, and the next version moves a board's item listing.

And one that is ours: Monday is a weekday. The app is labelled monday.com,
so "every Monday at 9" never reads as somebody naming it.
"""
import json
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import account_summary as acc
import agent_jev
import app_triage
import connections as C
import connector_drill
import mytools
import skill_fit

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")


class _R:
    """Just enough of an httpx response for _refusal and _vendor_said."""

    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


# --- the credential --------------------------------------------------------

def test_monday_is_a_provider_labelled_monday_dot_com():
    p = C.provider("monday")
    assert p is not None and p.label == "monday.com"


def test_the_token_is_sent_bare_with_the_version_pinned():
    auth = C.vendor_auth("monday", {"token": "eyJabc"})
    assert auth.base_url == "https://api.monday.com"
    assert auth.headers["Authorization"] == "eyJabc"
    assert auth.headers["API-Version"] == C.MONDAY_API_VERSION == "2026-10"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("monday", {})
    assert "token" in str(e.value)


def test_the_form_says_where_the_token_lives():
    p = C.provider("monday")
    assert [f.name for f in p.fields] == ["token"]
    assert "Developers" in p.where and "API token" in p.where


def test_the_probe_asks_who_the_token_belongs_to():
    p = C.provider("monday")
    assert (p.probe_path, p.probe_method) == ("/v2", "POST")
    assert "me" in p.probe_body["query"]


def test_the_card_is_named_after_the_account():
    payload = {"data": {"me": {"id": "1", "name": "Me", "email": "me@x.com"}}}
    assert C.account_label("monday", payload) == "me@x.com"
    # monday's refusal has "data": [], a list. Reading it must not raise;
    # with no name to show, the card falls back to the app's own label.
    assert C.account_label("monday", {"data": [], "errors": [{}]}) == "monday.com"


# --- a refusal that says 200 ----------------------------------------------

MONDAY_REFUSAL = {"data": [], "errors": [{
    "message": "User unauthorized to perform action",
    "extensions": {"code": "UserUnauthorizedException", "status_code": 403}}],
    "account_id": 123456}


def test_mondays_documented_refusal_is_a_refusal():
    assert C.graphql_refused(MONDAY_REFUSAL) is True
    said = mytools._refusal(_R(200, MONDAY_REFUSAL), "monday.com",
                            {"token": "eyJabc"}, "monday", "create_item",
                            writes=True)
    assert said and "User unauthorized" in said


def test_linears_refusal_still_is_one():
    assert C.graphql_refused({"data": None, "errors": [{"message": "x"}]})
    assert C.graphql_refused({"data": {"issueCreate": None},
                              "errors": [{"message": "x"}]})


def test_a_partial_answer_and_a_clean_one_are_not_refusals():
    assert not C.graphql_refused({"data": {"me": {"id": "1"}},
                                  "errors": [{"message": "asset gone"}]})
    assert not C.graphql_refused({"data": {"me": {"id": "1"}}})
    assert not C.graphql_refused({"data": []})
    assert not C.graphql_refused([])


async def test_connecting_with_a_token_monday_refuses_is_not_connected(
        monkeypatch):
    """The connect check read only the status code, so a 200 carrying
    errors saved a credential that could not say who it belonged to."""
    import routes_connections as RC

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, *a, **k):
            return _R(200, MONDAY_REFUSAL)

    async def _no_problem(url):
        return None

    monkeypatch.setattr(RC.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(RC.host_guard, "problem", _no_problem)
    ok, label, error = await RC._ask_vendor(C.provider("monday"),
                                            {"token": "eyJabc"})
    assert ok is False and label is None
    assert "monday.com" in error and "eyJabc" not in error


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["monday"]:
        if t.name == name:
            return t
    raise AssertionError("no such monday tool: " + name)


READS = {"whoami", "list_boards", "get_board", "list_items", "search_items",
         "get_item"}
WRITES = {"create_item", "update_item", "move_item", "comment_on_item"}


def test_the_tools_are_six_reads_and_four_writes_and_no_delete():
    names = {t.name for t in mytools.PROVIDER_TOOLS["monday"]}
    assert names == READS | WRITES
    writes = {t.name for t in mytools.PROVIDER_TOOLS["monday"]
              if mytools._writes(t)}
    assert writes == WRITES, "a read here is a POST and must say so"


def test_every_tool_posts_to_the_one_endpoint_with_variables():
    args = {"board_id": "123", "item_id": "456", "text": "x", "name": "x",
            "body": "x", "group_id": "topics",
            "column_values": {"status": "Done"}}
    for t in mytools.PROVIDER_TOOLS["monday"]:
        assert (t.method, t.path) == ("POST", "/v2"), t.name
        body = mytools._payload_for(t, args)
        assert "query" in body and isinstance(body["variables"], dict), t.name


def test_nothing_a_model_writes_is_pasted_into_the_query():
    nasty = 'x") { id } } mutation { delete_board(board_id: 1) { id } #'
    for name, args in (("search_items", {"board_id": "1", "text": nasty}),
                       ("create_item", {"board_id": "1", "name": nasty}),
                       ("comment_on_item", {"item_id": "1", "body": nasty})):
        body = mytools._payload_for(_tool(name), args)
        assert nasty not in body["query"], name
        assert "delete_board" not in body["query"], name


def test_an_id_must_be_a_number():
    with pytest.raises(ValueError) as e:
        mytools._payload_for(_tool("get_board"), {"board_id": "Marketing"})
    assert "number" in str(e.value)
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("get_item"), {"item_id": " "})


def test_column_values_travel_as_a_json_string_keyed_by_column_id():
    body = mytools._payload_for(_tool("create_item"), {
        "board_id": "123", "name": "Call the client",
        "column_values": {"status": "Working on it", "date4": "2026-12-01",
                          "text": ""}})
    assert body["variables"]["board"] == "123"
    assert body["variables"]["name"] == "Call the client"
    cv = body["variables"]["cv"]
    assert isinstance(cv, str), "monday takes column_values as a STRING"
    assert json.loads(cv) == {"status": "Working on it", "date4": "2026-12-01"}
    assert "group" not in body["variables"], "left out means the top group"


def test_column_values_given_as_a_json_string_are_read_too():
    body = mytools._payload_for(_tool("update_item"), {
        "board_id": "1", "item_id": "2",
        "column_values": '{"status": {"label": "Done"}}'})
    assert json.loads(body["variables"]["cv"]) == {"status": {"label": "Done"}}


def test_column_values_that_are_not_an_object_are_refused_with_an_example():
    with pytest.raises(ValueError) as e:
        mytools._payload_for(_tool("update_item"), {
            "board_id": "1", "item_id": "2", "column_values": "Done"})
    assert "get_board" in str(e.value)


def test_a_rename_is_the_name_column():
    body = mytools._payload_for(_tool("update_item"), {
        "board_id": "1", "item_id": "2", "name": "New name"})
    assert json.loads(body["variables"]["cv"]) == {"name": "New name"}
    assert "change_multiple_column_values" in body["query"]


def test_an_update_with_nothing_to_change_is_refused():
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("update_item"), {"board_id": "1",
                                                    "item_id": "2"})


def test_a_new_item_needs_a_name():
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("create_item"), {"board_id": "1"})


def test_search_looks_in_the_name_with_contains_text():
    body = mytools._payload_for(_tool("search_items"),
                                {"board_id": "1", "text": " invoice "})
    assert body["variables"]["qp"] == {"rules": [{
        "column_id": "name", "compare_value": ["invoice"],
        "operator": "contains_text"}]}
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("search_items"), {"board_id": "1",
                                                     "text": " "})


def test_the_next_page_is_asked_for_by_cursor_alone():
    """monday does not take a board and a cursor in the same request."""
    first = mytools._payload_for(_tool("list_items"), {"board_id": "1"})
    assert "items_page" in first["query"] and "cursor" not in first["variables"]
    nxt = mytools._payload_for(_tool("list_items"),
                               {"board_id": "1", "cursor": "MSw5Nzg"})
    assert "next_items_page" in nxt["query"]
    assert nxt["variables"] == {"c": "MSw5Nzg", "n": mytools.MAX_ITEMS}


def test_answers_are_dug_out_to_the_thing_asked_for():
    items = {"cursor": None, "items": [{"id": "9", "name": "x"}]}
    assert _tool("list_boards").unwrap(
        {"data": {"boards": [{"id": "1"}]}}) == [{"id": "1"}]
    assert _tool("get_board").unwrap(
        {"data": {"boards": [{"id": "1", "columns": []}]}}) == {
        "id": "1", "columns": []}
    assert _tool("list_items").unwrap(
        {"data": {"boards": [{"items_page": items}]}}) == items
    assert _tool("list_items").unwrap(
        {"data": {"next_items_page": items}}) == items
    assert _tool("get_item").unwrap(
        {"data": {"items": [{"id": "9"}]}}) == {"id": "9"}
    assert _tool("create_item").unwrap(
        {"data": {"create_item": {"id": "9"}}}) == {"id": "9"}


def test_an_id_nobody_can_see_says_so_instead_of_an_empty_envelope():
    out = _tool("get_board").unwrap({"data": {"boards": []}})
    assert "not_found" in out
    assert "not_found" in _tool("get_item").unwrap({"data": {"items": []}})


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_monday_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'monday'" in l]
    assert line and "real: true" in line[0] and "token: true" in line[0]
    assert "name: 'monday.com'" in line[0]


def test_mcp_proxy_can_reach_the_monday_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-monday"' in src
    assert 'MCP_MYTOOLS_URL + "/monday"' in src


def test_the_triage_agent_knows_what_monday_is_for():
    app = app_triage.APPS.get("monday")
    assert app is not None and app.label == "monday.com"
    assert "board" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["monday"]}
    assert "delete" in app.cannot.lower()


@pytest.mark.parametrize("said", [
    "every Monday at 9 read my email", "remind me on Monday",
    "send the report Monday morning"])
def test_the_weekday_never_names_the_app(said):
    app = app_triage.APPS["monday"]
    assert not app_triage._named(app, said)
    assert not any(w in said.lower() for w in app.says)


def test_naming_the_app_names_it():
    assert app_triage._named(app_triage.APPS["monday"],
                             "add this to my monday.com board")


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "monday.com" in note.lower()


def test_it_counts_as_a_task_tracker_for_the_tracker_skills():
    assert "monday" in skill_fit.TRACKERS
    assert "monday.com" in skill_fit.LABELS[skill_fit.TRACKER]
    assert "monday.com" in skill_fit.MENTIONS[skill_fit.TRACKER]
    assert "monday" not in skill_fit.MENTIONS[skill_fit.TRACKER], \
        "the bare word is a weekday"
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "var AIUI_TRACKERS" in l]
    assert line and "'monday'" in line[0]


def test_the_drill_can_find_a_board_without_losing_trellos():
    F = connector_drill.FROM_RESULT
    assert ("list_boards", "id") in F["board_id"]
    assert ("list_my_boards", "id") in F["board_id"]


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "monday" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("monday")["label"] == "monday.com"
