"""Todoist: your own tasks and projects, as you, with a personal token.

The tenth task tracker, and one that needs no app registration: every
Todoist account has a personal API token under Settings > Integrations >
Developer, and the Connections panel already takes personal tokens for
Trello, ClickUp and Airtable. So it works the moment it deploys.

Three vendor facts, each a connector that silently does not work if it is
got wrong:

**The API is v1 at /api/v1.** REST v2 and Sync v9 were folded into it, and
v1 refuses the old numeric ids. A connector written against the REST v2
examples still all over the web talks to the wrong API.

**Lists come wrapped**, as `{"results": [...], "next_cursor": ...}`. Read
as a bare list, every listing is one object with two keys and no task in it.

**Priority runs backwards from what a person says.** In the app, p1 is the
red, urgent one. In the API, urgent is `priority: 4` and normal is 1. A
model told "make it p1" writes 1, which is the LOWEST, so the shaping is on
this side where it can be read and tested.
"""
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


# --- the credential --------------------------------------------------------

def test_todoist_is_a_provider():
    assert C.provider("todoist") is not None


def test_it_signs_as_a_bearer_token_at_api_v1():
    auth = C.vendor_auth("todoist", {"token": "0123abcd"})
    assert auth.base_url == "https://api.todoist.com/api/v1"
    assert auth.headers["Authorization"] == "Bearer 0123abcd"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("todoist", {})
    assert "token" in str(e.value)


def test_the_form_asks_for_one_token_and_says_where_it_lives():
    p = C.provider("todoist")
    assert [f.name for f in p.fields] == ["token"]
    assert "Integrations" in p.where and "Developer" in p.where


def test_the_probe_asks_todoist_who_this_is():
    p = C.provider("todoist")
    assert p.probe_path == "/user"
    assert p.probe_method == "GET"


def test_the_card_is_named_after_the_account():
    assert C.account_label("todoist", {"email": "me@example.com",
                                       "full_name": "Me"}) == "me@example.com"
    assert C.account_label("todoist", {"full_name": "Me"}) == "Me"


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["todoist"]:
        if t.name == name:
            return t
    raise AssertionError("no such todoist tool: " + name)


READS = {"list_projects", "list_sections", "list_tasks", "find_tasks",
         "get_task", "whoami"}
WRITES = {"create_task", "update_task", "move_task", "complete_task",
          "reopen_task", "comment_on_task"}


def test_the_tools_are_six_reads_and_six_writes():
    """Counted, so a seventh write has to come here and be deliberate. A
    write is what needs an approval and a line in the catalogue. There is
    no delete, on purpose: completing a task is how Todoist retires one,
    and it can be reopened."""
    names = {t.name for t in mytools.PROVIDER_TOOLS["todoist"]}
    assert names == READS | WRITES
    writes = {t.name for t in mytools.PROVIDER_TOOLS["todoist"]
              if mytools._writes(t)}
    assert writes == WRITES


def test_every_path_is_v1_shaped():
    paths = {t.name: (t.method, t.path)
             for t in mytools.PROVIDER_TOOLS["todoist"]}
    assert paths["whoami"] == ("GET", "/user")
    assert paths["list_projects"] == ("GET", "/projects")
    assert paths["list_sections"] == ("GET", "/sections")
    assert paths["list_tasks"] == ("GET", "/tasks")
    assert paths["find_tasks"] == ("GET", "/tasks/filter")
    assert paths["get_task"] == ("GET", "/tasks/{task_id}")
    assert paths["create_task"] == ("POST", "/tasks")
    assert paths["update_task"] == ("POST", "/tasks/{task_id}")
    assert paths["move_task"] == ("POST", "/tasks/{task_id}/move")
    assert paths["complete_task"] == ("POST", "/tasks/{task_id}/close")
    assert paths["reopen_task"] == ("POST", "/tasks/{task_id}/reopen")
    assert paths["comment_on_task"] == ("POST", "/comments")


def test_a_listing_is_dug_out_of_its_results_envelope():
    payload = {"results": [{"id": "6X7", "content": "Call the bank"}],
               "next_cursor": None}
    for name in ("list_projects", "list_sections", "list_tasks",
                 "find_tasks"):
        assert _tool(name).unwrap(payload) == payload["results"], name


def test_a_bare_list_still_reads_as_a_list():
    """Not every answer is wrapped. Unwrapping one that is not must hand it
    back as it came rather than lose it."""
    bare = [{"id": "1"}]
    assert _tool("list_tasks").unwrap(bare) == bare


def test_a_task_keeps_what_a_person_asks_about():
    keep = set(_tool("list_tasks").keep)
    assert {"id", "content", "due", "priority", "project_id",
            "checked"} <= keep


def test_the_filter_is_sent_as_the_query_param():
    assert mytools._query_for(_tool("find_tasks"),
                              {"filter": "today | overdue"}) == {
        "query": "today | overdue", "limit": mytools.MAX_ITEMS}


def test_a_project_filter_goes_in_the_query_string():
    assert mytools._query_for(_tool("list_tasks"),
                              {"project_id": "6Jf8"}) == {
        "project_id": "6Jf8", "limit": mytools.MAX_ITEMS}


def test_the_filter_argument_tells_the_model_the_syntax():
    desc = _tool("find_tasks").args["filter"][1]
    assert "today | overdue" in desc


# --- priority, which runs backwards --------------------------------------

@pytest.mark.parametrize("said,api", [
    ("p1", 4), ("P1", 4), ("urgent", 4),
    ("p2", 3), ("high", 3),
    ("p3", 2), ("medium", 2),
    ("p4", 1), ("normal", 1), ("low", 1),
])
def test_a_priority_said_the_way_the_app_says_it_is_turned_around(said, api):
    assert mytools._todoist_priority(said) == api


def test_a_number_is_read_as_the_apps_p_number_too():
    """"priority 1" from a person means p1, the urgent one. Read as the
    API's 1 it is the lowest priority there is."""
    assert mytools._todoist_priority(1) == 4
    assert mytools._todoist_priority("4") == 1


def test_a_priority_nobody_can_read_is_refused_with_the_choices():
    with pytest.raises(ValueError) as e:
        mytools._todoist_priority("whenever")
    assert "p1" in str(e.value)


# --- the bodies -----------------------------------------------------------

def test_a_new_task_is_sent_with_its_fields():
    body = mytools._todoist_task_body({
        "content": "Send the invoice", "description": "to Acme",
        "project_id": "6Jf8", "due": "tomorrow 9am", "priority": "p1",
        "labels": "money, admin"})
    assert body == {"content": "Send the invoice", "description": "to Acme",
                    "project_id": "6Jf8", "due_string": "tomorrow 9am",
                    "priority": 4, "labels": ["money", "admin"]}


def test_labels_may_arrive_as_a_list():
    body = mytools._todoist_task_body({"content": "x",
                                       "labels": ["a", " b "]})
    assert body["labels"] == ["a", "b"]


def test_an_empty_field_is_left_out_rather_than_blanked():
    """Sending description "" on an update would wipe the one already
    there, for a person who only asked to change the due date."""
    body = mytools._todoist_task_body({"task_id": "9", "due": "friday",
                                       "description": ""}, new=False)
    assert body == {"due_string": "friday"}


def test_a_new_task_with_no_words_is_refused():
    with pytest.raises(ValueError):
        mytools._todoist_task_body({"content": "  "})


def test_an_update_never_carries_the_project():
    """v1 moves a task with /move; a project_id on an update is ignored, so
    a model that thinks it moved the task would be told it had."""
    body = mytools._todoist_task_body({"task_id": "9", "content": "x",
                                       "project_id": "6Jf8"}, new=False)
    assert "project_id" not in body and "task_id" not in body


def test_an_update_with_nothing_to_change_is_refused():
    with pytest.raises(ValueError):
        mytools._todoist_task_body({"task_id": "9"}, new=False)


def test_a_move_needs_somewhere_to_go():
    assert mytools._todoist_move_body({"task_id": "9",
                                       "project_id": "6Jf8"}) == {
        "project_id": "6Jf8"}
    with pytest.raises(ValueError):
        mytools._todoist_move_body({"task_id": "9"})


def test_a_comment_names_its_task():
    assert mytools._payload_for(_tool("comment_on_task"),
                                {"task_id": "9", "text": "done?"}) == {
        "task_id": "9", "content": "done?"}


# --- a write that answers with nothing ----------------------------------

def test_completing_a_task_says_done_not_nothing_found():
    """Todoist answers close and reopen with 204 and no body. The fallback
    for an empty body used to ask `tool.writes`, which is None on almost
    every write, so the model was told `items: []`, the answer to a search
    that found nothing, after completing a task."""
    for name in ("complete_task", "reopen_task"):
        assert mytools._no_body_result(_tool(name)) == {"ok": True,
                                                        "done": True}, name


def test_an_empty_read_still_says_nothing_was_found():
    assert mytools._no_body_result(_tool("list_tasks")) == {"ok": True,
                                                           "items": []}


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_todoist_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'todoist'" in l]
    assert line, "no todoist card in the Connections panel"
    assert "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_todoist_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-todoist"' in src
    assert 'MCP_MYTOOLS_URL + "/todoist"' in src


def test_the_triage_agent_knows_what_todoist_is_for():
    app = app_triage.APPS.get("todoist")
    assert app is not None
    assert "to-do" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["todoist"]}
    assert "delete" in app.cannot.lower()


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "todoist" in note.lower()


def test_it_counts_as_a_task_tracker_for_the_tracker_skills():
    assert "todoist" in skill_fit.TRACKERS
    assert "Todoist" in skill_fit.LABELS[skill_fit.TRACKER]
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "var AIUI_TRACKERS" in l]
    assert line and "'todoist'" in line[0], (
        "a tracker the chat does not carry on after connecting")


def test_the_drill_can_find_a_project_and_a_task_to_read():
    assert ("list_projects", "id") in connector_drill.FROM_RESULT["project_id"]
    assert ("list_tasks", "id") in connector_drill.FROM_RESULT["task_id"]


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "todoist" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("todoist")["label"] == "Todoist"
