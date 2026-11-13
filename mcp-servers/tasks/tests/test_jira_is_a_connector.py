"""Jira, the first of the six apps whose card said Coming soon.

Three things in here are not guesses and are worth keeping, because each
one is a way this connector would have been silently wrong:

**The API version is the one that changed under everybody.** Jira Cloud
REMOVED `/rest/api/3/search`; the replacement is `/rest/api/3/search/jql`,
with `nextPageToken` instead of `startAt`
(confluence.atlassian.com/jirakb/run-jql-search-query-using-jira-cloud-rest-api-1289424308.html).
A connector written from memory reaches the dead one.

**v3 takes rich text, not text.** A description or a comment on v3 must be
an Atlassian Document Format document. A plain string is a 400, so the
shaping is on this side where it can be tested, exactly as Airtable's
field types are.

**A search is a POST here.** `/search/jql` takes GET or POST, and POST is
the only one that can carry a default `fields` list without hoping the
model sends one. That makes `method` a bad proxy for "this writes
something", which matters because a 403 on a write suggests reconnecting
and a 403 on a read must not.
"""
import base64
import os
from json import dumps as json_dumps

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import account_summary as acc
import agent_jev
import app_triage
import connections as C
import mytools

CREDS = {"site_url": "https://aiui.atlassian.net",
         "email": "me@example.com",
         "token": "tok-123"}

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")


# --- the credential --------------------------------------------------------

def test_jira_is_a_provider_anybody_can_connect():
    p = C.provider("jira")
    assert p is not None, "jira is not in connections.PROVIDERS"
    assert [f.name for f in p.fields] == ["site_url", "email", "token"]


def test_it_signs_requests_as_basic_auth_over_email_and_token():
    """Jira Cloud's documented token path is basic auth, email as the user
    and the API token as the password. Bearer is for OAuth, which is the
    second half of this work, not this card."""
    auth = C.vendor_auth("jira", CREDS)
    expected = base64.b64encode(b"me@example.com:tok-123").decode()
    assert auth.headers["Authorization"] == "Basic " + expected
    assert auth.params == {}, "nothing may ride in the query string"


def test_the_base_url_is_the_v3_rest_root_of_that_persons_own_site():
    auth = C.vendor_auth("jira", CREDS)
    assert auth.base_url == "https://aiui.atlassian.net/rest/api/3"


def test_a_trailing_slash_on_the_site_does_not_double_up():
    auth = C.vendor_auth("jira", dict(CREDS, site_url="https://aiui.atlassian.net/"))
    assert auth.base_url == "https://aiui.atlassian.net/rest/api/3"


def test_a_missing_token_is_refused_before_anything_leaves_the_box():
    """The message has to name the field. "Unknown provider" is what this
    raised while jira did not exist, so asserting only ValueError passes
    on an empty registry and proves nothing."""
    with pytest.raises(ValueError) as e:
        C.vendor_auth("jira", {"site_url": "https://aiui.atlassian.net",
                               "email": "me@example.com"})
    assert "token" in str(e.value)


def test_a_site_that_is_not_a_url_is_refused():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("jira", dict(CREDS, site_url="aiui"))
    assert "http" in str(e.value).lower()


def test_the_url_error_names_a_jira_site_and_not_an_n8n_one():
    """The shared validator's example used to be n8n's, which is the wrong
    thing to show somebody connecting Jira."""
    try:
        C.vendor_auth("jira", dict(CREDS, site_url="nope"))
    except ValueError as e:
        assert "atlassian.net" in str(e)
    else:
        raise AssertionError("a bad site URL was accepted")


def test_the_token_is_redacted_and_the_site_is_not():
    out = C.redact("jira", CREDS)
    assert "tok-123" not in str(out)
    assert out["site_url"] == "https://aiui.atlassian.net"


def test_the_card_shows_which_account_is_connected():
    assert C.account_label("jira", {"displayName": "Ralph Benitez",
                                    "emailAddress": "r@example.com"}) \
        == "Ralph Benitez"
    assert C.account_label("jira", {"emailAddress": "r@example.com"}) \
        == "r@example.com"


def test_the_probe_asks_jira_who_this_credential_is():
    assert C.provider("jira").probe_path == "/myself"


def test_where_to_get_the_token_names_atlassians_own_page():
    where = C.provider("jira").where
    assert "id.atlassian.com" in where
    assert "api-token" in where.replace(" ", "-").lower()


# --- the tools -------------------------------------------------------------

def test_the_tools_exist_and_read_before_they_write():
    names = [t.name for t in mytools.PROVIDER_TOOLS["jira"]]
    assert names[:3] == ["list_my_projects", "search_issues", "get_issue"]
    assert set(names) == {"list_my_projects", "search_issues", "get_issue",
                          "create_issue", "comment_on_issue", "whoami"}


def test_search_goes_to_the_endpoint_that_still_exists():
    """`/rest/api/3/search` is REMOVED from Jira Cloud. A connector pointing
    at it fails for everybody, on every site, for ever."""
    tool = _tool("search_issues")
    assert tool.path == "/search/jql"
    assert tool.method == "POST"


def test_search_always_asks_for_fields_even_when_nobody_names_any():
    """The new endpoint returns bare ids and keys unless `fields` is given,
    so a search with none is a list of issue keys and nothing a person
    asked about."""
    body = mytools._jira_search_body({"jql": "project = IO"})
    assert body["jql"] == "project = IO"
    assert "summary" in body["fields"] and "status" in body["fields"]


def test_a_model_may_name_its_own_fields_either_way_round():
    """A list is the documented shape and a comma string is what a model
    writes half the time."""
    assert mytools._jira_search_body(
        {"jql": "x", "fields": ["summary"]})["fields"] == ["summary"]
    assert mytools._jira_search_body(
        {"jql": "x", "fields": "summary, status"})["fields"] == ["summary",
                                                                 "status"]


def test_search_never_asks_for_more_rows_than_we_will_show():
    body = mytools._jira_search_body({"jql": "x", "limit": 5000})
    assert body["maxResults"] == mytools.MAX_ITEMS


def test_reading_one_issue_does_not_drag_back_every_custom_field():
    """A bare GET of an issue returns every field the site has, custom ones
    included. That is hundreds of keys into a model's context for a
    question about a summary and a status."""
    tool = _tool("get_issue")
    assert tool.method == "GET"
    assert tool.query_defaults.get("fields"), (
        "get_issue must ask for named fields, or it returns the lot")


def test_a_default_query_value_is_sent_when_the_caller_gave_none():
    sent = mytools._query_for(_tool("get_issue"), {"issue_key": "IO-1"})
    assert "summary" in sent["fields"]


def test_a_caller_who_names_fields_keeps_them():
    sent = mytools._query_for(_tool("get_issue"),
                              {"issue_key": "IO-1", "fields": "status"})
    assert sent["fields"] == "status"


# --- rich text, which v3 demands -------------------------------------------

def test_a_description_is_sent_as_a_document_not_a_string():
    body = mytools._jira_issue_body({"project_key": "IO",
                                     "summary": "The page is blank",
                                     "description": "It happens on reload."})
    fields = body["fields"]
    assert fields["project"] == {"key": "IO"}
    assert fields["summary"] == "The page is blank"
    doc = fields["description"]
    assert doc["type"] == "doc" and doc["version"] == 1
    assert doc["content"][0]["content"][0]["text"] == "It happens on reload."


def test_an_issue_type_is_always_sent_because_jira_requires_one():
    body = mytools._jira_issue_body({"project_key": "IO", "summary": "x"})
    assert body["fields"]["issuetype"] == {"name": "Task"}
    body = mytools._jira_issue_body({"project_key": "IO", "summary": "x",
                                     "issue_type": "Bug"})
    assert body["fields"]["issuetype"] == {"name": "Bug"}


def test_no_description_sends_no_description_at_all():
    """An empty document is not an empty string to Jira: a text node with
    no text is invalid and the whole create is a 400."""
    body = mytools._jira_issue_body({"project_key": "IO", "summary": "x",
                                     "description": "   "})
    assert "description" not in body["fields"]


def test_blank_lines_become_separate_paragraphs():
    doc = mytools._jira_adf("One.\n\nTwo.")
    assert len(doc["content"]) == 2
    assert doc["content"][1]["content"][0]["text"] == "Two."


def test_text_pasted_from_windows_splits_the_same_way():
    """A paste carries \\r\\n, and "\\r\\n\\r\\n" holds no "\\n\\n" to split
    on, so the whole thing would have arrived as one paragraph with
    carriage returns inside the text node."""
    doc = mytools._jira_adf("One.\r\n\r\nTwo.")
    assert len(doc["content"]) == 2
    assert doc["content"][1]["content"][0]["text"] == "Two."
    assert "\r" not in json_dumps(doc)


def test_a_comment_is_a_document_too():
    body = mytools._jira_comment_body({"issue_key": "IO-1",
                                       "comment": "Looking at it now."})
    assert body["body"]["content"][0]["content"][0]["text"] \
        == "Looking at it now."


def test_a_comment_with_no_text_is_not_sent_as_an_invalid_document():
    assert mytools._jira_comment_body({"issue_key": "IO-1",
                                       "comment": ""}) == {}


# --- a POST is not always a write ------------------------------------------

def test_a_search_is_not_treated_as_a_write():
    """`writes` drives one sentence: a 403 on a write says "reconnect it to
    allow that". On a search, a 403 means this person cannot see that
    project, and sending them to reconnect is a wrong instruction."""
    assert mytools._writes(_tool("search_issues")) is False
    assert mytools._writes(_tool("create_issue")) is True
    assert mytools._writes(_tool("get_issue")) is False


def test_every_other_post_in_the_catalogue_still_counts_as_a_write():
    """The override must be opt-in, or one new field quietly turns every
    vendor write into a read."""
    reads = [(pid, t.name) for pid, tools in mytools.PROVIDER_TOOLS.items()
             for t in tools
             if str(t.method).upper() != "GET" and not mytools._writes(t)]
    assert reads == [("jira", "search_issues")], reads


# --- the rest of the wiring, which is where connectors go wrong ------------

def test_the_panel_offers_jira_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'jira'" in l]
    assert line, "no jira card in the Connections panel"
    assert "real: true" in line[0] and "token: true" in line[0]


def test_no_card_claims_to_be_real_without_a_connector_behind_it():
    """A Connect button with no provider is a dead end, and the six Coming
    soon cards are exactly that shape waiting to happen."""
    src = open(PANEL, encoding="utf-8").read()
    claimed = set()
    for line in src.splitlines():
        if "real: true" in line and "id: '" in line:
            claimed.add(line.split("id: '", 1)[1].split("'", 1)[0])
    unbacked = sorted(claimed - set(C.PROVIDERS) - {"google"})
    assert unbacked == [], (
        "marked real with no entry in connections.PROVIDERS: "
        + ", ".join(unbacked))


# --- when Jira says no, it says why in its own shape --------------------
# Jira answers a bad create with {"errorMessages": [...], "errors":
# {"field": "..."}} and NOTHING in _vendor_said read either key, so the
# single most likely failure on a real site, a project whose create screen
# requires a field we did not send, would have come back as "Jira returned
# an error (400)." with the reason thrown away. That is the exact bug the
# function was written to stop, in a new vendor's dialect.


class _Resp:
    def __init__(self, payload, status=400):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_a_jira_field_error_is_repeated_to_the_person():
    said = mytools._vendor_said(
        _Resp({"errorMessages": [],
               "errors": {"summary": "You must specify a summary of the "
                                     "issue."}}), {})
    assert "must specify a summary" in said


def test_a_jira_field_error_names_the_field_it_is_about():
    """"Field 'duedate' cannot be set" is actionable; the message alone is
    not, when a project requires three custom fields."""
    said = mytools._vendor_said(
        _Resp({"errors": {"duedate": "Field 'duedate' cannot be set."}}), {})
    assert "duedate" in said


def test_jiras_general_message_is_used_when_there_is_no_field_error():
    said = mytools._vendor_said(
        _Resp({"errorMessages": ["Issue type is a sub-task but parent issue "
                                 "key or id not specified."],
               "errors": {}}), {})
    assert "parent issue key" in said


def test_a_vendor_message_carrying_the_credential_is_still_suppressed():
    """The rule that makes repeating a vendor safe at all has to cover the
    new keys too, or a vendor echoing the request puts a token in a chat."""
    said = mytools._vendor_said(
        _Resp({"errorMessages": ["bad token abcdef1234567890"]}),
        {"token": "abcdef1234567890"})
    assert said == ""


TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")


def test_mcp_proxy_has_a_server_for_every_provider_we_wrote_tools_for():
    """The step that makes tools REACHABLE, and the one with nothing
    watching it until now.

    A provider can be in PROVIDER_TOOLS, serve a correct openapi.json, pass
    every test in this file, and still be unusable by any model, because
    mcp-proxy only knows the servers listed in its own registry. Nothing
    errors: the tools are simply never discovered, never indexed, never
    searchable. That is the same silence as a tool nobody refreshed.

    Read as text rather than imported: mcp-proxy is a separate build
    context with its own dependencies, and this check is about one line of
    its registry.
    """
    src = open(TENANTS, encoding="utf-8").read()
    missing = [pid for pid in sorted(mytools.PROVIDER_TOOLS)
               if ('server_id="my-' + pid + '"') not in src
               or ('MCP_MYTOOLS_URL + "/' + pid + '"') not in src]
    assert missing == [], (
        "mcp-proxy has no per-user server for: " + ", ".join(missing)
        + ". Add it to ALL_SERVERS in mcp-proxy/tenants.py, or no model can "
          "reach these tools.")


def test_the_triage_agent_knows_what_jira_is_for():
    app = app_triage.APPS.get("jira")
    assert app is not None, "jira is not in the triage catalogue"
    for word in ("issue", "bug", "sprint"):
        assert word in app.note.lower(), word


def test_what_it_says_it_can_do_rests_on_tools_that_exist():
    names = {t.name for t in mytools.PROVIDER_TOOLS["jira"]}
    assert set(app_triage.APPS["jira"].tools) <= names


def test_it_says_out_loud_what_it_cannot_do_yet():
    """Moving an issue through a workflow and assigning one both need a
    second call to look an id up first, so neither is here. An assistant
    that implies otherwise sends somebody to check a board that never
    changed."""
    cannot = app_triage.APPS["jira"].cannot.lower()
    assert "status" in cannot or "transition" in cannot
    assert "assign" in cannot


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "jira" in note.lower()


def test_the_assistant_counts_jira_among_the_apps_you_can_connect():
    assert "jira" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("jira")["label"] == "Jira"
    assert acc.connect_hint("jira")["where"] == C.provider("jira").where


def _tool(name):
    for t in mytools.PROVIDER_TOOLS["jira"]:
        if t.name == name:
            return t
    raise AssertionError("no such jira tool: " + name)
