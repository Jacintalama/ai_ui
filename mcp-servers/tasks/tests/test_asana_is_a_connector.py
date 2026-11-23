"""Asana: your own tasks and projects, as you, with a personal access token.

The eleventh task tracker, and like Todoist it needs no app registration:
every Asana user can make a personal access token in the developer
console (app.asana.com/0/my-apps), so it works the day it deploys.

Four vendor facts, each a connector that silently does not work if it is
got wrong:

**Everything is wrapped in `data`**, both ways. An answer is
`{"data": ...}`, and a write is refused unless its body is `{"data": {...}}`
too. Sent flat, every create is a 400 after the person approved it.

**"My tasks" needs `assignee=me` AND `workspace`, together.** Either one
alone is a 400, so the workspace has to be asked for, never left out.

**A project's task list includes finished tasks** unless
`completed_since=now` is sent, so "what is open in this project" would
come back padded with work done years ago.

**Search is premium only.** A free account answers 402, so there is no
search tool: it would fail for most of the people who try it.

**A due date is a calendar date**, `due_on` as YYYY-MM-DD. Asana does not
read "tomorrow", so a date that is not one is refused here with a
sentence, before the person approves a write that cannot succeed.
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

def test_asana_is_a_provider():
    assert C.provider("asana") is not None


def test_it_signs_as_a_bearer_token_at_api_1_0():
    auth = C.vendor_auth("asana", {"token": "2/123/456:abc"})
    assert auth.base_url == "https://app.asana.com/api/1.0"
    assert auth.headers["Authorization"] == "Bearer 2/123/456:abc"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("asana", {})
    assert "token" in str(e.value)


def test_the_form_asks_for_one_token_and_says_where_it_lives():
    p = C.provider("asana")
    assert [f.name for f in p.fields] == ["token"]
    assert "app.asana.com/0/my-apps" in p.where


def test_the_probe_is_a_plain_path():
    """httpx DROPS a query string written into the URL whenever `params`
    is passed, even an empty dict, and the probe always passes one. So
    `/users/me?opt_fields=email` would arrive as `/users/me`, and a label
    built on the email would be blank for a reason nothing shows."""
    p = C.provider("asana")
    assert p.probe_path == "/users/me"
    assert "?" not in p.probe_path


def test_the_card_is_named_after_the_account_inside_data():
    assert C.account_label("asana", {"data": {"gid": "1", "name": "Me",
                                              "email": "me@x.com"}}) == "me@x.com"
    assert C.account_label("asana", {"data": {"gid": "1",
                                              "name": "Me"}}) == "Me"
    assert C.account_label("asana", {}) == "Asana", (
        "nothing to read falls back to the app's own name")


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["asana"]:
        if t.name == name:
            return t
    raise AssertionError("no such asana tool: " + name)


READS = {"whoami", "list_workspaces", "list_projects", "list_sections",
         "list_project_tasks", "my_tasks", "get_task"}
WRITES = {"create_task", "update_task", "complete_task", "reopen_task",
          "move_to_section", "comment_on_task"}


def test_the_tools_are_seven_reads_and_six_writes():
    """Counted, so another write has to come here and be deliberate. No
    delete, on purpose: completing is how a task is retired and it can be
    reopened. No search either: it is premium only."""
    names = {t.name for t in mytools.PROVIDER_TOOLS["asana"]}
    assert names == READS | WRITES
    writes = {t.name for t in mytools.PROVIDER_TOOLS["asana"]
              if mytools._writes(t)}
    assert writes == WRITES


def test_the_paths_are_asanas():
    paths = {t.name: (t.method, t.path)
             for t in mytools.PROVIDER_TOOLS["asana"]}
    assert paths["whoami"] == ("GET", "/users/me")
    assert paths["list_workspaces"] == ("GET", "/workspaces")
    assert paths["list_projects"] == ("GET", "/projects")
    assert paths["list_sections"] == ("GET", "/projects/{project_id}/sections")
    assert paths["list_project_tasks"] == ("GET", "/projects/{project_id}/tasks")
    assert paths["my_tasks"] == ("GET", "/tasks")
    assert paths["get_task"] == ("GET", "/tasks/{task_id}")
    assert paths["create_task"] == ("POST", "/tasks")
    assert paths["update_task"] == ("PUT", "/tasks/{task_id}")
    assert paths["complete_task"] == ("PUT", "/tasks/{task_id}")
    assert paths["reopen_task"] == ("PUT", "/tasks/{task_id}")
    assert paths["move_to_section"] == ("POST", "/sections/{section_id}/addTask")
    assert paths["comment_on_task"] == ("POST", "/tasks/{task_id}/stories")


def test_every_answer_is_dug_out_of_data():
    for t in mytools.PROVIDER_TOOLS["asana"]:
        assert t.unwrap is not None, t.name
        assert t.unwrap({"data": [{"gid": "1"}], "next_page": None}) == [
            {"gid": "1"}], t.name
        assert t.unwrap({"data": {"gid": "1"}}) == {"gid": "1"}, t.name


def test_no_search_tool_because_search_is_premium_only():
    for t in mytools.PROVIDER_TOOLS["asana"]:
        assert "search" not in t.path, t.name


def test_my_tasks_asks_for_the_workspace_and_sends_me():
    t = _tool("my_tasks")
    assert t.args["workspace_id"][2] is True, (
        "assignee=me without a workspace is a 400")
    q = mytools._query_for(t, {"workspace_id": "W1"})
    assert q["assignee"] == "me" and q["workspace"] == "W1"


def test_open_tasks_only_unless_asked():
    for name in ("my_tasks", "list_project_tasks"):
        q = mytools._query_for(_tool(name), {"workspace_id": "W1",
                                             "project_id": "P1"})
        assert q["completed_since"] == "now", name


def test_a_task_listing_asks_for_the_fields_a_person_reads():
    """Asana's compact answer is gid, name and resource_type and nothing
    else. Without opt_fields a list of tasks has no due date, no assignee
    and no link in it."""
    q = mytools._query_for(_tool("list_project_tasks"), {"project_id": "P1"})
    for field in ("due_on", "assignee.name", "completed", "permalink_url"):
        assert field in q["opt_fields"], field
    assert q["limit"] == mytools.MAX_ITEMS


def test_projects_are_listed_per_workspace_and_not_archived():
    t = _tool("list_projects")
    assert t.args["workspace_id"][2] is True
    q = mytools._query_for(t, {"workspace_id": "W1"})
    assert q["workspace"] == "W1" and q["archived"] == "false"


# --- the bodies -----------------------------------------------------------

def test_a_new_task_is_wrapped_in_data_with_its_project():
    body = mytools._asana_task_body({
        "name": "Send the invoice", "notes": "to Acme",
        "project_id": "P1", "due_on": "2026-11-24", "assignee": "me"})
    assert body == {"data": {"name": "Send the invoice", "notes": "to Acme",
                             "projects": ["P1"], "due_on": "2026-11-24",
                             "assignee": "me"}}


def test_a_new_task_with_no_project_goes_to_the_workspace():
    body = mytools._asana_task_body({"name": "x", "workspace_id": "W1"})
    assert body == {"data": {"name": "x", "workspace": "W1"}}


def test_a_new_task_with_nowhere_to_live_is_refused():
    """Every Asana task belongs to a workspace, through a project or
    directly. Without either the create is a 400 after approval."""
    with pytest.raises(ValueError) as e:
        mytools._asana_task_body({"name": "x"})
    assert "project_id" in str(e.value) and "workspace_id" in str(e.value)


def test_a_new_task_with_no_name_is_refused():
    with pytest.raises(ValueError):
        mytools._asana_task_body({"name": " ", "project_id": "P1"})


@pytest.mark.parametrize("given", ["tomorrow", "24/11/2026", "Nov 24",
                                   "2026-13-01"])
def test_a_due_date_that_is_not_a_date_is_refused_with_the_form(given):
    with pytest.raises(ValueError) as e:
        mytools._asana_task_body({"name": "x", "project_id": "P1",
                                  "due_on": given})
    assert "YYYY-MM-DD" in str(e.value)


def test_an_update_sends_only_what_changed():
    """An empty field is left out: notes "" would wipe the description of
    somebody who only asked to change the due date."""
    body = mytools._asana_task_body({"task_id": "T1", "due_on": "2026-12-01",
                                     "notes": ""}, new=False)
    assert body == {"data": {"due_on": "2026-12-01"}}


def test_an_update_never_moves_the_task():
    """`projects` and `workspace` are create-only to Asana."""
    body = mytools._asana_task_body({"task_id": "T1", "name": "x",
                                     "project_id": "P1",
                                     "workspace_id": "W1"}, new=False)
    assert body == {"data": {"name": "x"}}


def test_an_update_with_nothing_to_change_is_refused():
    with pytest.raises(ValueError):
        mytools._asana_task_body({"task_id": "T1"}, new=False)


def test_completing_and_reopening_send_the_completed_flag():
    assert mytools._payload_for(_tool("complete_task"), {"task_id": "T1"}) == {
        "data": {"completed": True}}
    assert mytools._payload_for(_tool("reopen_task"), {"task_id": "T1"}) == {
        "data": {"completed": False}}


def test_moving_to_a_section_names_the_task():
    assert mytools._payload_for(_tool("move_to_section"),
                                {"section_id": "S1", "task_id": "T1"}) == {
        "data": {"task": "T1"}}


def test_a_comment_is_wrapped_and_not_empty():
    assert mytools._payload_for(_tool("comment_on_task"),
                                {"task_id": "T1", "text": "done?"}) == {
        "data": {"text": "done?"}}
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("comment_on_task"),
                             {"task_id": "T1", "text": " "})


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_asana_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'asana'" in l]
    assert line, "no asana card in the Connections panel"
    assert "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_asana_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-asana"' in src
    assert 'MCP_MYTOOLS_URL + "/asana"' in src


def test_the_triage_agent_knows_what_asana_is_for():
    app = app_triage.APPS.get("asana")
    assert app is not None
    assert "team" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["asana"]}
    assert "delete" in app.cannot.lower() and "search" in app.cannot.lower()


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "asana" in note.lower()


def test_it_counts_as_a_task_tracker_for_the_tracker_skills():
    assert "asana" in skill_fit.TRACKERS
    assert "Asana" in skill_fit.LABELS[skill_fit.TRACKER]
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "var AIUI_TRACKERS" in l]
    assert line and "'asana'" in line[0]


def test_the_drill_can_find_a_workspace_project_and_task():
    F = connector_drill.FROM_RESULT
    assert ("list_workspaces", "gid") in F["workspace_id"]
    assert ("list_projects", "gid") in F["project_id"]
    assert ("list_project_tasks", "gid") in F["task_id"]
    assert ("list_sections", "gid") in F["section_id"]


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "asana" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("asana")["label"] == "Asana"
