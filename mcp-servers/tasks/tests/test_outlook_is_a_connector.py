"""Outlook: read and send your mail, and see your calendar, as you.

Half of business is not on Gmail. This is the other half, and it is one
OAuth app for mail, calendar and contacts.

Five things here are vendor facts rather than choices, each read off
Microsoft's own reference on 2026-11-16, and each one a connector that
silently does not work if it is got wrong:

**The env names must not collide with the sign-in app.** `_env_names`
derives `<PROVIDER>_CLIENT_ID`, and `MICROSOFT_CLIENT_ID` is already set on
this box: it powers Open WebUI's "Continue with Microsoft" button, a
`consumers`-tenant app registered against `/oauth/microsoft/callback` with
no Graph permissions at all. A provider called `microsoft` would therefore
read `configured() is True` on day one and offer a one-click button that
cannot work, using the credentials of the thing everybody signs in with.
So the provider is `outlook`.

**`sendMail` returns 202 with an EMPTY BODY.** Our `_call` falls back to
`{"items": []}` when a body will not parse, which for a send reads like
"nothing found" rather than "sent". A model told `items: []` after being
asked to send an email has every reason to try again.

**`calendarView` REQUIRES startDateTime and endDateTime**, and it is the
only endpoint that expands recurring events into their occurrences.
`/me/events` returns the series master, so "what is on my calendar
tomorrow" asked against `/me/events` misses every recurring meeting, which
for most people is most of the calendar.

**A pasted token is not an option.** A Graph access token lasts about an
hour, so a paste form would work for one meeting and then read "Needs
reconnecting" for ever. OAuth only, and `offline_access` is what returns
the refresh token the renewal machinery needs.

**The tenant decides who can connect.** `consumers` is personal accounts
only, `organizations` is work and school only, `common` is both. The
sign-in app is on `consumers`; this one must not inherit that.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C
import mytools
import oauth_providers as O

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")

GRAPH = "https://graph.microsoft.com/v1.0"


# --- the credential --------------------------------------------------------

def test_outlook_is_a_provider():
    assert C.provider("outlook") is not None, \
        "outlook is not in connections.PROVIDERS"


def test_it_signs_as_a_bearer_token_at_the_graph_host():
    auth = C.vendor_auth("outlook", {"token": "eyJ0.tok"})
    assert auth.base_url == GRAPH
    assert auth.headers["Authorization"] == "Bearer eyJ0.tok"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(Exception) as e:
        C.vendor_auth("outlook", {})
    assert "token" in str(e.value)


def test_the_probe_asks_graph_who_this_is():
    assert C.provider("outlook").probe_path == "/me"


def test_the_card_is_named_after_the_account():
    read = C.provider("outlook").read_label
    assert read({"userPrincipalName": "ralph@contoso.com"}) \
        == "ralph@contoso.com"
    # Personal accounts often have no userPrincipalName worth showing.
    assert read({"mail": "ralph@outlook.com"}) == "ralph@outlook.com"
    assert read({"displayName": "Ralph"}) == "Ralph"
    assert read({}) == ""


def test_there_is_no_paste_form_for_outlook():
    """A Graph access token lasts about an hour. A paste form would be a
    connection that dies the same afternoon, every time."""
    assert C.provider("outlook").fields == []


# --- the env names, which is the trap this connector was born in ----------

def test_it_does_not_borrow_the_sign_in_apps_credentials():
    cid, csec = O._env_names("outlook")
    assert cid == "OUTLOOK_CLIENT_ID"
    assert csec == "OUTLOOK_CLIENT_SECRET"
    assert "MICROSOFT" not in cid and "MICROSOFT" not in csec, (
        "MICROSOFT_CLIENT_ID is Open WebUI's sign-in app: consumers tenant, "
        "no Graph permissions, a different redirect. Borrowing it would "
        "offer a one-click button that cannot work.")


def test_the_tenant_is_not_read_from_the_sign_in_apps_variable(monkeypatch):
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "consumers")
    assert "consumers" not in O.OUTLOOK_AUTHORITY, (
        "the sign-in app is registered for personal accounts only; this "
        "connector must not inherit that")


def test_the_authority_lets_both_work_and_personal_accounts_in():
    assert "/common/" in O.OUTLOOK_AUTHORITY, (
        "common is both account kinds. organizations excludes personal "
        "Outlook.com, consumers excludes every business.")


# --- the OAuth entry ------------------------------------------------------

def test_the_endpoints_are_microsofts_own():
    p = O.PROVIDERS["outlook"]
    assert p.authorize_endpoint.startswith(
        "https://login.microsoftonline.com/")
    assert p.authorize_endpoint.endswith("/oauth2/v2.0/authorize")
    assert p.token_endpoint.endswith("/oauth2/v2.0/token")


def test_the_authorize_url_asks_for_offline_access():
    """Without it Graph returns an access token good for about an hour and
    NO refresh token, so the connection cannot be renewed by anything."""
    assert "offline_access" in O.OUTLOOK_SCOPE.split()


def test_the_scope_is_what_the_tools_use_and_nothing_else():
    asked = set(O.OUTLOOK_SCOPE.split())
    assert asked == {
        "offline_access", "User.Read", "Mail.Read", "Mail.Send",
        "Calendars.ReadWrite", "Contacts.Read",
    }, "asking for a permission no tool uses is permission we should not hold"


def test_it_does_not_ask_for_file_access_it_has_no_tools_for():
    assert not any(s.startswith("Files.") for s in O.OUTLOOK_SCOPE.split())


def test_the_token_response_keeps_the_refresh_token_and_the_expiry():
    """Graph's access token lasts about an hour, so the refresh token is
    the whole connection. It arrives exactly once, in this response, and
    one thrown away here cannot be recovered afterwards.

    The expiry is stored ABSOLUTE (`expires_at`), not as the relative
    `expires_in` Microsoft sends: a number of seconds is only meaningful
    next to the moment it was issued, and that moment is not stored.
    """
    import time

    creds, label = O.PROVIDERS["outlook"].read_token({
        "access_token": "eyJ0.acc",
        "refresh_token": "0.AR0A-long",
        "expires_in": 3599,
        "token_type": "Bearer",
        "scope": "Mail.Read Mail.Send",
    })
    assert creds["token"] == "eyJ0.acc"
    assert creds["refresh_token"] == "0.AR0A-long"
    assert float(creds["expires_at"]) > time.time(), \
        "an expiry already in the past would make every call renew first"


# --- the calendar window, which Graph refuses to guess ---------------------

def test_a_calendar_read_always_carries_a_window():
    """startDateTime and endDateTime are REQUIRED query parameters. Graph
    answers 400 without them, so the tool supplies a default rather than
    letting a model find that out."""
    body = mytools._outlook_window({})
    assert "startDateTime" in body and "endDateTime" in body
    assert body["startDateTime"] < body["endDateTime"]


def test_the_window_is_offset_aware_so_graph_does_not_assume_utc():
    """A value with no offset is read as UTC, which silently shifts
    somebody's day by up to 13 hours."""
    body = mytools._outlook_window({})
    assert body["startDateTime"].endswith("Z") or \
        ("+" in body["startDateTime"][10:] or
         "-" in body["startDateTime"][10:])


def test_a_caller_may_name_its_own_window():
    body = mytools._outlook_window({"start": "2026-11-16T00:00:00Z",
                                    "end": "2026-11-17T00:00:00Z"})
    assert body["startDateTime"] == "2026-11-16T00:00:00Z"
    assert body["endDateTime"] == "2026-11-17T00:00:00Z"


def test_the_calendar_tool_reads_calendarview_not_events():
    """calendarView expands recurring events into occurrences. /me/events
    returns the series master, so a week with four standups shows one."""
    tool = _tool("list_events")
    assert "calendarView" in tool.path
    assert tool.path != "/me/events"


# --- sending, where the answer is 202 and nothing else --------------------

def test_the_send_body_is_the_shape_graph_documents():
    body = mytools._outlook_send_body({
        "to": "ralph@example.com", "subject": "Hi", "body": "Hello"})
    msg = body["message"]
    assert msg["subject"] == "Hi"
    assert msg["body"]["content"] == "Hello"
    assert msg["toRecipients"] == [
        {"emailAddress": {"address": "ralph@example.com"}}]


def test_several_recipients_can_be_given_in_one_string():
    body = mytools._outlook_send_body({
        "to": "a@x.com, b@y.com", "subject": "s", "body": "b"})
    got = [r["emailAddress"]["address"] for r in body["message"]["toRecipients"]]
    assert got == ["a@x.com", "b@y.com"]


def test_a_send_is_marked_as_a_write():
    assert _tool("send_mail").writes is True


def test_a_write_that_answers_with_no_body_says_it_was_done():
    """Graph answers sendMail with 202 and an empty body. The generic
    fallback for an unparseable body is `items: []`, which for a send reads
    as "nothing found" and invites the model to try again."""
    out = mytools._no_body_result(_tool("send_mail"))
    assert out["ok"] is True
    assert out.get("done") is True
    assert "items" not in out, \
        "an empty list is the answer to a search, not to a send"


def test_a_read_that_answers_with_no_body_still_says_nothing_found():
    out = mytools._no_body_result(_tool("list_mail"))
    assert out["ok"] is True
    assert out["items"] == []
    assert "done" not in out


# --- the tools ------------------------------------------------------------

def _tool(name):
    for t in mytools.PROVIDER_TOOLS["outlook"]:
        if t.name == name:
            return t
    raise AssertionError("no outlook tool called %r; there are: %s"
                         % (name, [t.name for t in
                                   mytools.PROVIDER_TOOLS["outlook"]]))


def test_outlook_has_tools_at_all():
    assert mytools.PROVIDER_TOOLS.get("outlook"), \
        "outlook is not in PROVIDER_TOOLS, so no my-outlook_* tool exists"


def test_the_tools_cover_mail_calendar_and_contacts():
    names = {t.name for t in mytools.PROVIDER_TOOLS["outlook"]}
    assert {"whoami", "list_mail", "search_mail", "send_mail",
            "list_events", "create_event", "list_contacts"} <= names


def test_only_sending_and_creating_are_writes():
    writes = {t.name for t in mytools.PROVIDER_TOOLS["outlook"] if t.writes}
    assert writes == {"send_mail", "create_event"}


def test_a_mail_listing_is_dug_out_of_the_odata_envelope():
    """Graph wraps every collection in {"value": [...]}."""
    tool = _tool("list_mail")
    assert tool.unwrap is not None
    assert tool.unwrap({"value": [{"id": "1"}]}) == [{"id": "1"}]
    assert tool.unwrap({}) == []


def test_a_mail_listing_keeps_the_fields_a_person_asked_about():
    keep = _tool("list_mail").keep
    for f in ("subject", "from", "receivedDateTime"):
        assert f in keep


# --- the rest of the wiring ----------------------------------------------

def test_the_panel_offers_outlook_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    assert "'outlook'" in src or '"outlook"' in src, \
        "the Connections grid has no Outlook card"


def test_mcp_proxy_can_reach_the_outlook_tools():
    tenants = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")
    src = open(tenants, encoding="utf-8").read()
    assert "outlook" in src, \
        "mcp-proxy will not route my-outlook_* without an entry here"
