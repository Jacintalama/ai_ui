"""Linear: issues for product teams, as you, with a personal API key.

The first GraphQL connector. Every call is a POST of a query to one
endpoint, so four things here are not like any connector before it:

**A personal key goes in Authorization with NO "Bearer".** Bearer is for
OAuth access tokens; a personal key sent as Bearer is refused.

**A refusal can arrive as HTTP 200**, with `{"errors": [...]}` and no
data. Every refusal check before this one read the status code, so a
failed create would have reached the model as a success.

**Every read is a POST**, so each one says `writes=False`, or a refusal
on a listing would tell somebody to reconnect so IO can write.

**An issue is named by its identifier**, "ENG-123", and Linear's own
`issue(id:)` takes that as well as the UUID, so the model never has to
look an id up first.
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


class _R:
    """Just enough of an httpx response for _refusal and _vendor_said."""

    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


# --- the credential --------------------------------------------------------

def test_linear_is_a_provider():
    assert C.provider("linear") is not None


def test_a_personal_key_is_sent_bare_not_as_bearer():
    auth = C.vendor_auth("linear", {"token": "lin_api_abc"})
    assert auth.base_url == "https://api.linear.app"
    assert auth.headers["Authorization"] == "lin_api_abc"
    assert auth.params == {}


def test_a_missing_key_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("linear", {})
    assert "token" in str(e.value)


def test_the_form_says_where_the_key_lives():
    p = C.provider("linear")
    assert [f.name for f in p.fields] == ["token"]
    assert "Security" in p.where


def test_the_probe_asks_for_the_viewer():
    p = C.provider("linear")
    assert p.probe_path == "/graphql"
    assert p.probe_method == "POST"
    assert "viewer" in p.probe_body["query"]


def test_the_card_is_named_after_the_viewer():
    payload = {"data": {"viewer": {"id": "u1", "name": "Me",
                                   "email": "me@x.com"}}}
    assert C.account_label("linear", payload) == "me@x.com"


# --- a refusal that says 200 ----------------------------------------------

def test_a_graphql_refusal_with_status_200_is_a_refusal():
    r = _R(200, {"data": None,
                 "errors": [{"message": "Entity not found: Issue"}]})
    said = mytools._refusal(r, "Linear", {"token": "lin_api_abc"},
                            "linear", "get_issue")
    assert said and "Entity not found" in said


def test_a_root_field_that_came_back_null_is_a_refusal_too():
    r = _R(200, {"data": {"issueCreate": None},
                 "errors": [{"message": "teamId must be a UUID"}]})
    said = mytools._refusal(r, "Linear", {}, "linear", "create_issue",
                            writes=True)
    assert "teamId must be a UUID" in said


def test_an_answer_with_data_is_not_a_refusal():
    r = _R(200, {"data": {"viewer": {"id": "u1"}}})
    assert mytools._refusal(r, "Linear", {}, "linear", "whoami") == ""


def test_a_list_of_errors_is_read_for_its_messages():
    r = _R(400, {"errors": [{"message": "a"}, {"message": "b"}]})
    assert mytools._vendor_said(r, {}) == " a; b"


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["linear"]:
        if t.name == name:
            return t
    raise AssertionError("no such linear tool: " + name)


READS = {"whoami", "list_teams", "list_states", "my_issues", "team_issues",
         "search_issues", "get_issue"}
WRITES = {"create_issue", "update_issue", "comment_on_issue"}


def test_the_tools_are_seven_reads_and_three_writes():
    names = {t.name for t in mytools.PROVIDER_TOOLS["linear"]}
    assert names == READS | WRITES
    writes = {t.name for t in mytools.PROVIDER_TOOLS["linear"]
              if mytools._writes(t)}
    assert writes == WRITES, "a read here is a POST and must say so"


def test_every_tool_posts_a_query_to_the_one_endpoint():
    for t in mytools.PROVIDER_TOOLS["linear"]:
        assert (t.method, t.path) == ("POST", "/graphql"), t.name
        body = mytools._payload_for(t, {"team_id": "T", "issue": "ENG-1",
                                        "text": "x", "title": "x",
                                        "body": "x"})
        assert "query" in body, t.name


def test_my_issues_leaves_out_what_is_finished():
    q = mytools._payload_for(_tool("my_issues"), {})["query"]
    assert "assignedIssues" in q
    assert "completed" in q and "canceled" in q and "nin" in q


def test_an_issue_is_asked_for_by_its_identifier():
    body = mytools._payload_for(_tool("get_issue"), {"issue": " ENG-123 "})
    assert body["variables"] == {"id": "ENG-123"}


def test_search_uses_the_current_endpoint_not_the_deprecated_one():
    q = mytools._payload_for(_tool("search_issues"), {"text": "login"})["query"]
    assert "searchIssues" in q and "issueSearch" not in q


def test_a_search_with_no_words_is_refused():
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("search_issues"), {"text": " "})


def test_answers_are_dug_out_to_the_list_or_the_thing():
    nodes = [{"identifier": "ENG-1"}]
    assert _tool("my_issues").unwrap(
        {"data": {"viewer": {"assignedIssues": {"nodes": nodes}}}}) == nodes
    assert _tool("team_issues").unwrap(
        {"data": {"team": {"issues": {"nodes": nodes}}}}) == nodes
    assert _tool("search_issues").unwrap(
        {"data": {"searchIssues": {"nodes": nodes}}}) == nodes
    assert _tool("get_issue").unwrap(
        {"data": {"issue": {"identifier": "ENG-1"}}}) == {"identifier": "ENG-1"}
    assert _tool("create_issue").unwrap(
        {"data": {"issueCreate": {"success": True,
                                  "issue": {"identifier": "ENG-2"}}}}) == {
        "identifier": "ENG-2"}


# --- priority and dates ----------------------------------------------------

@pytest.mark.parametrize("said,api", [
    ("urgent", 1), ("Urgent", 1), ("1", 1), (1, 1),
    ("high", 2), ("medium", 3), ("low", 4),
    ("none", 0), ("no priority", 0), (0, 0),
])
def test_a_priority_is_linears_number(said, api):
    assert mytools._linear_priority(said) == api


def test_a_priority_nobody_can_read_is_refused():
    with pytest.raises(ValueError) as e:
        mytools._linear_priority("soonish")
    assert "urgent" in str(e.value)


def test_a_new_issue_names_its_team_and_title():
    body = mytools._payload_for(_tool("create_issue"), {
        "team_id": "T1", "title": "Login is broken",
        "description": "on Safari", "priority": "high",
        "due_date": "2026-12-01", "state_id": "S1"})
    assert body["variables"] == {"input": {
        "teamId": "T1", "title": "Login is broken",
        "description": "on Safari", "priority": 2,
        "dueDate": "2026-12-01", "stateId": "S1"}}
    assert "issueCreate" in body["query"]


def test_a_new_issue_without_a_team_or_title_is_refused():
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("create_issue"), {"title": "x"})
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("create_issue"), {"team_id": "T1"})


def test_a_due_date_must_be_a_date():
    with pytest.raises(ValueError) as e:
        mytools._payload_for(_tool("create_issue"), {
            "team_id": "T1", "title": "x", "due_date": "next week"})
    assert "YYYY-MM-DD" in str(e.value)


def test_an_update_sends_only_what_changed():
    body = mytools._payload_for(_tool("update_issue"), {
        "issue": "ENG-7", "state_id": "S2", "description": ""})
    assert body["variables"] == {"id": "ENG-7", "input": {"stateId": "S2"}}


def test_an_update_with_nothing_to_change_is_refused():
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("update_issue"), {"issue": "ENG-7"})


def test_a_comment_names_its_issue_and_says_something():
    body = mytools._payload_for(_tool("comment_on_issue"),
                                {"issue": "ENG-7", "body": "on it"})
    assert body["variables"] == {"input": {"issueId": "ENG-7",
                                           "body": "on it"}}
    with pytest.raises(ValueError):
        mytools._payload_for(_tool("comment_on_issue"),
                             {"issue": "ENG-7", "body": " "})


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_linear_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'linear'" in l]
    assert line and "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_linear_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-linear"' in src
    assert 'MCP_MYTOOLS_URL + "/linear"' in src


def test_the_triage_agent_knows_what_linear_is_for():
    app = app_triage.APPS.get("linear")
    assert app is not None
    assert "issue" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["linear"]}
    assert "delete" in app.cannot.lower()


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "linear" in note.lower()


def test_it_counts_as_a_task_tracker_for_the_tracker_skills():
    assert "linear" in skill_fit.TRACKERS
    assert "Linear" in skill_fit.LABELS[skill_fit.TRACKER]
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "var AIUI_TRACKERS" in l]
    assert line and "'linear'" in line[0]


def test_the_drill_can_find_a_team_and_an_issue():
    F = connector_drill.FROM_RESULT
    assert ("list_teams", "id") in F["team_id"]
    assert ("my_issues", "identifier") in F["issue"]


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "linear" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("linear")["label"] == "Linear"
