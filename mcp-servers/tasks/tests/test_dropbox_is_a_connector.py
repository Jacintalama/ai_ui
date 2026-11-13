"""Dropbox: find and read ABOUT your files, as you.

Second of the six Coming-soon apps. Four things here are vendor facts
rather than choices, and each one is a connector that silently does not
work if it is got wrong:

**A pasted token is not an option.** Creating long-lived access tokens is
deprecated and a token generated in the App Console is short-lived,
roughly four hours, with an `sl.` prefix. So unlike Jira there is no
paste form worth having: it would work for one afternoon and then read
"Needs reconnecting" for ever. This connector is OAuth only, and
`token_access_type=offline` is what returns the long-lived refresh token
that the renewal machinery then uses.

**The root folder is the empty string.** `"/"` is not the root to
Dropbox, it is an invalid path, and "Documents" without a leading slash
is invalid too. A model asked to list somebody's files will write one of
those, so the shaping is on this side.

**Everything is a POST**, even a read, and the arguments go in a JSON
body rather than a query string.

**search_v2 buries each file two levels down**, under
`matches[].metadata.metadata`, so the unwrapping has to reach it or every
result is an envelope with nothing readable in it.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import account_summary as acc
import agent_jev
import app_triage
import connections as C
import mytools
import oauth_providers as O
import oauth_refresh as F

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")

TOKEN_RESPONSE = {
    "access_token": "sl.ABC...",
    "refresh_token": "long-lived-refresh",
    "expires_in": 14400,
    "token_type": "bearer",
    "scope": "account_info.read files.metadata.read",
    "account_id": "dbid:AAB...",
    "uid": "123",
}


# --- the credential --------------------------------------------------------

def test_dropbox_is_a_provider():
    p = C.provider("dropbox")
    assert p is not None, "dropbox is not in connections.PROVIDERS"


def test_it_signs_as_a_bearer_token_at_the_api_host():
    auth = C.vendor_auth("dropbox", {"token": "sl.tok"})
    assert auth.base_url == "https://api.dropboxapi.com/2"
    assert auth.headers["Authorization"] == "Bearer sl.tok"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("dropbox", {})
    assert "token" in str(e.value)


def test_the_probe_asks_dropbox_who_this_is():
    p = C.provider("dropbox")
    assert p.probe_path == "/users/get_current_account"
    assert p.probe_method == "POST", (
        "Dropbox has no GET endpoints; a GET probe is a 400 on every connect")


def test_the_card_is_named_after_the_account():
    label = C.account_label("dropbox", {
        "email": "me@example.com",
        "name": {"display_name": "Ralph Benitez"}})
    assert label == "me@example.com"
    assert C.account_label("dropbox", {
        "name": {"display_name": "Ralph Benitez"}}) == "Ralph Benitez"


def test_there_is_no_paste_form_for_dropbox():
    """A console token lasts about four hours. A form that takes one is a
    connection that reads Connected today and Needs reconnecting tomorrow,
    for ever, which is worse than no button at all."""
    assert C.provider("dropbox").fields == []
    assert O.supports_oauth("dropbox") is True


# --- the OAuth entry ------------------------------------------------------

def test_the_endpoints_are_dropboxs_own():
    p = O.PROVIDERS["dropbox"]
    assert p.authorize_endpoint == "https://www.dropbox.com/oauth2/authorize"
    assert p.token_endpoint == "https://api.dropboxapi.com/oauth2/token"


def test_the_authorize_url_asks_for_offline_access():
    """`token_access_type=offline` is the whole reason this is viable: it
    is what returns a refresh token. Without it the connection is dead in
    four hours and nothing can renew it."""
    url = O.authorize_url("dropbox", "cid",
                          "https://io.example/connect/dropbox/callback",
                          state="st")
    assert "token_access_type=offline" in url


def test_the_scope_is_what_the_four_tools_read_and_nothing_else():
    """Read-only on purpose. Upload, delete and share links each need
    another scope and each is a separate card, and a consent screen is
    something a person reads."""
    scope = set(O.DROPBOX_SCOPE.split())
    assert scope == {"account_info.read", "files.metadata.read"}


def test_the_token_response_keeps_the_refresh_token_and_the_expiry():
    values, label = O.read_token_response("dropbox", TOKEN_RESPONSE)
    assert values["token"] == TOKEN_RESPONSE["access_token"]
    assert values["refresh_token"] == TOKEN_RESPONSE["refresh_token"]
    assert float(values["expires_at"]) > 0
    assert F.refreshable("dropbox", values) is True


def test_a_renewal_sends_the_form_dropbox_documents(monkeypatch):
    monkeypatch.setenv("DROPBOX_CLIENT_ID", "cid")
    monkeypatch.setenv("DROPBOX_CLIENT_SECRET", "csec")
    values, _ = O.read_token_response("dropbox", TOKEN_RESPONSE)
    post = F.refresh_post("dropbox", values)
    assert post["url"] == "https://api.dropboxapi.com/oauth2/token"
    body = post["data"]
    assert body["grant_type"] == "refresh_token"
    assert body["client_id"] == "cid" and body["client_secret"] == "csec"


# --- the paths, which is where a model will go wrong ----------------------

def test_the_root_folder_is_the_empty_string():
    """"/" is NOT the root to Dropbox, it is an invalid path. A model asked
    to list somebody's files writes "/" about half the time."""
    for given in ("/", "", "   ", "root", "~"):
        assert mytools._dropbox_path(given) == "", given


def test_a_path_without_a_leading_slash_gets_one():
    assert mytools._dropbox_path("Documents") == "/Documents"
    assert mytools._dropbox_path("Documents/2026") == "/Documents/2026"


def test_a_trailing_slash_is_dropped():
    assert mytools._dropbox_path("/Documents/") == "/Documents"


def test_the_folder_listing_sends_a_path_and_a_cap():
    body = mytools._dropbox_folder_body({"path": "/"})
    assert body["path"] == ""
    assert body["limit"] == mytools.MAX_ITEMS
    assert body["recursive"] is False, (
        "recursive on a big account is a very long answer to "
        "'what is in my Dropbox'")


def test_a_caller_may_ask_for_fewer_rows_but_not_more():
    assert mytools._dropbox_folder_body({"path": "", "limit": 5})["limit"] == 5
    assert mytools._dropbox_folder_body(
        {"path": "", "limit": 9000})["limit"] == mytools.MAX_ITEMS


def test_the_search_sends_its_options_where_dropbox_wants_them():
    body = mytools._dropbox_search_body({"query": "invoice", "limit": 4})
    assert body["query"] == "invoice"
    assert body["options"]["max_results"] == 4


def test_a_search_with_no_words_is_not_sent_as_a_blank():
    """Dropbox answers 400 to an empty query, and the model has already
    spent a round by then."""
    assert mytools._dropbox_search_body({"query": "  "}) == {}


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["dropbox"]:
        if t.name == name:
            return t
    raise AssertionError("no such dropbox tool: " + name)


def test_the_tools_are_reads_only_for_now():
    names = {t.name for t in mytools.PROVIDER_TOOLS["dropbox"]}
    assert names == {"list_folder", "search_files", "get_metadata", "whoami"}


def test_every_call_is_a_post_because_dropbox_has_no_gets():
    for t in mytools.PROVIDER_TOOLS["dropbox"]:
        assert t.method == "POST", t.name


def test_a_read_that_is_a_post_is_not_treated_as_a_write():
    """Otherwise a 403 on a listing tells somebody to reconnect so IO can
    write, which is a wrong instruction: on Dropbox a 403 is a missing
    scope or a file they cannot see."""
    for name in ("list_folder", "search_files", "get_metadata", "whoami"):
        assert mytools._writes(_tool(name)) is False, name


def test_a_found_file_is_dug_out_of_two_envelopes():
    """search_v2 nests each result under matches[].metadata.metadata. One
    level of unwrapping leaves a list of envelopes with no name in them."""
    payload = {"matches": [
        {"metadata": {".tag": "metadata",
                      "metadata": {".tag": "file", "name": "invoice.pdf",
                                   "path_display": "/invoice.pdf"}}}]}
    got = _tool("search_files").unwrap(payload)
    assert got == [{".tag": "file", "name": "invoice.pdf",
                    "path_display": "/invoice.pdf"}]


def test_a_listing_keeps_the_fields_a_person_asked_about():
    keep = set(_tool("list_folder").keep)
    assert {".tag", "name", "path_display"} <= keep, (
        ".tag is how a folder is told from a file")


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_dropbox_as_a_real_card():
    """`token: true` as well as `real: true`, and not because there is a
    token to paste. It is what makes the card open the connect panel at
    all: without it makeCard's click handler falls through to
    unifiedConnect(), which is GOOGLE's consent flow. A Dropbox card that
    starts a Google sign-in is worse than a card that does nothing.
    """
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'dropbox'" in l]
    assert line, "no dropbox card in the Connections panel"
    assert "real: true" in line[0] and "token: true" in line[0]


def test_an_app_with_no_form_and_no_oauth_yet_says_so():
    """Dropbox is the first provider with NO paste form at all, so it is
    the first that can be `real` on the card while this deployment cannot
    connect it. Both panels ask the server for the fields; with none, and
    with no OAuth app configured, they would draw an empty form with a
    Save button. It has to say what is actually true instead.
    """
    panel = open(PANEL, encoding="utf-8").read()
    agents = open(os.path.join(HERE, "..", "static", "agents.html"),
                  encoding="utf-8").read()
    for name, src in (("integrations-ui.js", panel), ("agents.html", agents)):
        assert "not set up on this server yet" in src, name


def test_mcp_proxy_can_reach_the_dropbox_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-dropbox"' in src
    assert 'MCP_MYTOOLS_URL + "/dropbox"' in src


def test_the_triage_agent_knows_what_dropbox_is_for():
    app = app_triage.APPS.get("dropbox")
    assert app is not None
    for word in ("file", "folder"):
        assert word in app.note.lower(), word
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["dropbox"]}


def test_it_says_out_loud_that_it_cannot_touch_the_files_themselves():
    cannot = app_triage.APPS["dropbox"].cannot.lower()
    assert "upload" in cannot or "change" in cannot
    assert "read the contents" in cannot or "download" in cannot


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "dropbox" in note.lower()


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "dropbox" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("dropbox")["label"] == "Dropbox"
