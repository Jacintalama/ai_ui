"""Jira by approving, instead of pasting a site address and a token.

The connector shipped first (test_jira_is_a_connector.py) and takes three
typed fields. This is the other half, and it is NOT the same request with
a different credential, because of one thing Atlassian does that no other
vendor here does:

**An OAuth token does not talk to your site.** The token comes back with
no idea which Jira it is for. A second call,
`api.atlassian.com/oauth/token/accessible-resources`, names the sites it
can reach and gives each a CLOUD ID, and every later call goes to
`api.atlassian.com/ex/jira/<cloudid>/rest/api/3`. So the callback has one
extra hop, the credential carries a cloud id, and `_jira_auth` has to
build two different base URLs depending on which kind of credential it is
holding.

Three parameters below are not decoration and each one is a silent
failure if it is missing:

  - `audience=api.atlassian.com`, or the token is issued for the wrong
    audience and every API call answers 401 with a working connection on
    the card.
  - `offline_access` in the scope, or no refresh token is ever issued and
    the connection dies in an hour with nothing able to renew it.
  - `prompt=consent`, or a second approval by somebody who has already
    approved returns no refresh token at all.
"""
import asyncio
import json
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C
import oauth_providers as O
import oauth_refresh as F
import routes_connections as R

#: Atlassian's documented token response.
TOKEN_RESPONSE = {
    "access_token": "eyJraWQiOiJ...",
    "refresh_token": "ATATT-refresh-...",
    "expires_in": 3600,
    "scope": "read:jira-work write:jira-work offline_access",
    "token_type": "Bearer",
}

#: What accessible-resources answers. The id is the cloud id; the url is
#: the site a person recognises.
SITES = [{"id": "cloud-abc-123", "name": "aiui",
          "url": "https://aiui.atlassian.net",
          "scopes": ["read:jira-work"], "avatarUrl": ""}]


# --- the provider entry ---------------------------------------------------

def test_jira_can_be_connected_by_approving():
    assert O.supports_oauth("jira") is True


def test_the_endpoints_are_atlassians_own():
    p = O.PROVIDERS["jira"]
    assert p.authorize_endpoint == "https://auth.atlassian.com/authorize"
    assert p.token_endpoint == "https://auth.atlassian.com/oauth/token"


def test_the_authorize_url_names_the_api_audience():
    """Without `audience=api.atlassian.com` the token is issued for the
    wrong audience: the connect succeeds, the card says Connected, and
    every single API call answers 401. There is nothing in the failure to
    point at this parameter, which is why it is asserted."""
    url = O.authorize_url("jira", "cid", "https://io.example/connect/jira/callback",
                          state="st")
    assert "audience=api.atlassian.com" in url


def test_the_authorize_url_asks_again_every_time():
    """`prompt=consent`. A second approval by somebody who has already
    approved returns NO refresh token otherwise, so a reconnect would
    quietly produce a credential that cannot be renewed."""
    url = O.authorize_url("jira", "cid", "https://io.example/cb", state="st")
    assert "prompt=consent" in url


def test_the_scope_asks_for_offline_access():
    """No refresh token is issued without it, and an Atlassian access
    token lasts an hour. A connection that dies in an hour with no way to
    renew it is worse than the paste form it replaces."""
    assert "offline_access" in O.JIRA_SCOPE


def test_the_scope_covers_what_the_six_tools_actually_call():
    """Reads for the four read tools, writes for create_issue and
    comment_on_issue, and the user scope so the card can name the account.
    Nothing beyond that: a consent screen is something a person reads."""
    scope = set(O.JIRA_SCOPE.split())
    assert {"read:jira-work", "write:jira-work", "offline_access"} <= scope
    assert not [s for s in scope if s.startswith("delete:")], (
        "nothing here deletes anything, so nothing should ask to")


def test_the_client_goes_in_the_body_as_json():
    """Atlassian documents a JSON body carrying client_id and
    client_secret, not HTTP Basic."""
    p = O.PROVIDERS["jira"]
    assert p.token_auth == "body"
    assert p.token_body == "json"
    assert O.client_in_body("jira") is True


def test_no_pkce_because_atlassian_does_not_ask_for_one():
    """A code_challenge sent to a vendor that never asked for one is an
    unknown parameter on somebody else's authorize URL."""
    assert O.PROVIDERS["jira"].pkce is False


# --- the token response ---------------------------------------------------

def test_the_refresh_token_and_the_expiry_are_both_kept():
    """The vendor sends a refresh token exactly once, in this response.
    One thrown away here cannot be recovered afterwards."""
    values, label = O.read_token_response("jira", TOKEN_RESPONSE)
    assert values["token"] == TOKEN_RESPONSE["access_token"]
    assert values["refresh_token"] == TOKEN_RESPONSE["refresh_token"]
    assert float(values["expires_at"]) > 0
    assert label == "", "the site's name comes from the cloud-id hop"


def test_a_response_with_no_token_is_refused():
    """Vendors answer 200 with an error body."""
    with pytest.raises(ValueError):
        O.read_token_response("jira", {"error": "invalid_grant"})


def test_a_refresh_can_be_asked_for_once_one_is_stored():
    values, _ = O.read_token_response("jira", TOKEN_RESPONSE)
    assert F.refreshable("jira", values) is True


def test_a_refresh_does_not_lose_the_cloud_id():
    """The renewal response carries a token and nothing else: no cloud id,
    no site. A credential rebuilt from it would have a token that works
    and no idea which Jira to send it to, which is a working connection
    that 404s on every call."""
    values, _ = O.read_token_response("jira", TOKEN_RESPONSE)
    values["cloud_id"] = "cloud-abc-123"
    values["site_url"] = "https://aiui.atlassian.net"
    fresh = F.after_refresh(values, {"access_token": "new", "expires_in": 3600})
    assert fresh["cloud_id"] == "cloud-abc-123"
    assert fresh["site_url"] == "https://aiui.atlassian.net"
    assert fresh["token"] == "new"


# --- signing a call with an OAuth credential ------------------------------

def test_an_oauth_credential_talks_to_the_api_host_not_the_site():
    """The whole reason this card is not just a provider entry."""
    auth = C.vendor_auth("jira", {"cloud_id": "cloud-abc-123",
                                  "token": "tok", "scheme": "bearer"})
    assert auth.base_url == \
        "https://api.atlassian.com/ex/jira/cloud-abc-123/rest/api/3"
    assert auth.headers["Authorization"] == "Bearer tok"


def test_an_oauth_credential_needs_no_site_address_or_email():
    """Those two are what the paste form asks for. An approval gives
    neither, and requiring them would refuse every one-click connection
    before a request left the box."""
    C.vendor_auth("jira", {"cloud_id": "c1", "token": "t",
                           "scheme": "bearer"})


def test_a_pasted_credential_still_signs_the_old_way():
    """Both kinds have to work: the people who connected with a token
    before one-click existed keep working."""
    auth = C.vendor_auth("jira", {"site_url": "https://aiui.atlassian.net",
                                  "email": "me@example.com", "token": "tok"})
    assert auth.base_url == "https://aiui.atlassian.net/rest/api/3"
    assert auth.headers["Authorization"].startswith("Basic ")


def test_a_cloud_id_that_is_not_one_is_refused():
    """It lands in a URL. Anything that could change the host, or add a
    path segment, must not get there.

    A site address is supplied as well, so the only thing wrong with each
    credential below is the cloud id. Without that this test passed on an
    empty registry, because a jira credential with no site address is
    refused for a different reason entirely.
    """
    for bad in ("../../evil", "a/b", "c?x=1", "c#f", "ev il"):
        with pytest.raises(ValueError):
            C.vendor_auth("jira", {"cloud_id": bad, "token": "t",
                                   "scheme": "bearer", "email": "m@e.c",
                                   "site_url": "https://aiui.atlassian.net"})


def test_a_renewal_is_the_request_atlassian_documents(monkeypatch):
    """`token_auth="body"` with a JSON body, which is what the generic
    renewal then builds: grant_type, the refresh token, and the client in
    the body rather than in a Basic header."""
    monkeypatch.setenv("JIRA_CLIENT_ID", "cid")
    monkeypatch.setenv("JIRA_CLIENT_SECRET", "csec")
    values, _ = O.read_token_response("jira", TOKEN_RESPONSE)
    post = F.refresh_post("jira", values)
    assert post["url"] == "https://auth.atlassian.com/oauth/token"
    body = post["json"]
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == TOKEN_RESPONSE["refresh_token"]
    assert body["client_id"] == "cid" and body["client_secret"] == "csec"
    assert "auth" not in post, "the client does not go in a Basic header"


# --- a refusal has to be readable ----------------------------------------
# The scope's spaces are encoded as `+` by urlencode, not as `%20`. RFC
# 6749 says these parameters are form-encoded, where `+` IS a space, and
# Airtable's live one-click proves the pattern works in practice, so this
# is almost certainly fine. Almost. If Atlassian disagrees the answer is
# `error=invalid_scope`, and until 2026-11-13 this page threw that away
# and said "Cancelled, or Jira refused the request", which is the same
# sentence somebody sees when they press Cancel. One of those is a bug in
# our URL and the other is a person changing their mind.


def test_a_vendors_reason_for_refusing_is_repeated():
    page = asyncio.run(R.oauth_callback(
        "jira", error="invalid_scope",
        error_description="The requested scope is invalid")).body.decode()
    assert "invalid_scope" in page or "scope is invalid" in page


def test_a_plain_cancel_still_reads_as_a_cancel():
    """Pressing Cancel sends `access_denied` and no description worth
    repeating. It must not start reading like a fault."""
    page = asyncio.run(R.oauth_callback(
        "jira", error="access_denied")).body.decode()
    assert "Cancelled" in page


def test_a_vendors_reason_cannot_close_the_script_block():
    """It is vendor text on its way into a page, through the same
    textContent path as every other message here."""
    page = asyncio.run(R.oauth_callback(
        "jira", error="x",
        error_description="</script><script>alert(1)</script>")).body.decode()
    assert "<script>alert(1)" not in page


def test_a_long_reason_is_cut_rather_than_pasted_whole(monkeypatch):
    page = asyncio.run(R.oauth_callback(
        "jira", error="x", error_description="y" * 900)).body.decode()
    assert "y" * 900 not in page


# --- the hop itself -------------------------------------------------------

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Client:
    """One fake httpx client, answering the two calls a connect makes."""

    def __init__(self, token=None, sites=None, sites_status=200):
        self.token = token if token is not None else TOKEN_RESPONSE
        self.sites = sites if sites is not None else SITES
        self.sites_status = sites_status
        self.seen = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **k):
        self.seen.append(("POST", url, k))
        return _Resp(self.token)

    async def get(self, url, **k):
        self.seen.append(("GET", url, k))
        return _Resp(self.sites, self.sites_status)

    async def request(self, method, url, **k):
        self.seen.append((method, url, k))
        return _Resp(self.sites, self.sites_status)


@pytest.fixture
def connect(monkeypatch):
    """The callback with the vendor and the database faked."""
    state = {"stored": [], "client": _Client()}

    async def _store(email, provider_id, values, label):
        state["stored"].append({"email": email, "provider": provider_id,
                                "values": dict(values), "label": label})

    monkeypatch.setattr(R, "_store_connection", _store)
    monkeypatch.setattr(R.httpx, "AsyncClient", lambda *a, **k: state["client"])
    monkeypatch.setenv("JIRA_CLIENT_ID", "cid")
    monkeypatch.setenv("JIRA_CLIENT_SECRET", "csec")
    state["token"] = O.STATES.mint("ralph@example.com")
    return state


def _run(connect):
    return asyncio.run(R.oauth_callback(
        "jira", code="c", state=connect["token"])).body.decode("utf-8")


def test_a_connect_asks_which_sites_the_token_can_reach(connect):
    page = _run(connect)
    asked = [u for m, u, _ in connect["client"].seen if "accessible" in u]
    assert asked, connect["client"].seen
    assert asked[0] == "https://api.atlassian.com/oauth/token/accessible-resources"
    assert "aiui" in page


def test_the_cloud_id_is_stored_beside_the_token(connect):
    _run(connect)
    assert len(connect["stored"]) == 1
    v = connect["stored"][0]["values"]
    assert v["cloud_id"] == "cloud-abc-123"
    assert v["site_url"] == "https://aiui.atlassian.net"
    assert v["scheme"] == "bearer"


def test_the_card_is_named_after_the_site(connect):
    _run(connect)
    assert connect["stored"][0]["label"] == "aiui"


def test_a_token_that_reaches_no_site_is_not_stored(connect):
    """Approved, token works, reaches nothing. The same shape as a GitHub
    App authorised but installed nowhere, and the same answer: refuse,
    rather than store a connection that passes every check we make and
    does nothing."""
    connect["client"] = _Client(sites=[])
    page = _run(connect)
    assert connect["stored"] == []
    assert "no jira site" in page.lower()


def test_a_hop_that_could_not_be_made_does_not_store_a_blind_credential(connect):
    """A credential with no cloud id cannot address any Jira, so storing
    it would produce a card saying Connected over a connection that 404s
    on every call."""
    connect["client"] = _Client(sites={"error": "nope"}, sites_status=500)
    _run(connect)
    assert connect["stored"] == []


def test_somebody_with_several_sites_is_told_which_one_was_picked(connect):
    """accessible-resources can name several. Silently taking the first is
    a connection to a site they did not choose, and they have no way to
    tell."""
    connect["client"] = _Client(sites=[
        dict(SITES[0]),
        {"id": "cloud-def-456", "name": "other", "url": "https://other.atlassian.net"},
    ])
    page = _run(connect)
    assert connect["stored"][0]["values"]["cloud_id"] == "cloud-abc-123"
    said = page.lower()
    assert "aiui" in said
    assert "2 " in said or "two" in said, (
        "it has to say there were others: " + said[-400:])


def test_the_token_request_carries_the_client_in_its_body(connect):
    _run(connect)
    posts = [k for m, u, k in connect["client"].seen if m == "POST"]
    assert posts, connect["client"].seen
    body = posts[0].get("json") or {}
    assert body.get("client_id") == "cid"
    assert body.get("client_secret") == "csec"
    assert body.get("grant_type") == "authorization_code"
    assert body.get("redirect_uri", "").endswith("/connect/jira/callback")


def test_nothing_in_the_page_came_from_the_vendor_unescaped(connect):
    """The site name is the vendor's, and it goes into a page."""
    connect["client"] = _Client(sites=[
        {"id": "c1", "name": "</script><script>alert(1)</script>",
         "url": "https://x.atlassian.net"}])
    page = _run(connect)
    assert "<script>alert(1)" not in page
    assert json.dumps("</script>")[1:-1] not in page or "u003c" in page
