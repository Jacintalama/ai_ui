"""LinkedIn: post as yourself, and read nothing but your own name.

Third of the six Coming-soon apps, and the narrowest connector here on
purpose. Read off LinkedIn's own documentation on 2026-11-13
(learn.microsoft.com/linkedin/consumer/integrations/self-serve/share-on-linkedin),
not from a guide:

**Only three permissions are open to every developer**: `openid`,
`profile` and `email` (Sign In with LinkedIn using OpenID Connect) and
`w_member_social` (Share on LinkedIn). Everything else, connections, a
company page, any analytics, is partner-gated. So this connector posts
and names you, and `cannot` says the rest out loud.

**The endpoint is `/v2/ugcPosts`**, and `X-Restli-Protocol-Version:
2.0.0` is required on every request. The newer `/rest/posts` belongs to
the Versioned API that Community Management uses, so a connector written
from the newest-looking docs asks for access we do not have.

**A share needs the author's Person URN**, which is `urn:li:person:` plus
the `sub` from `/v2/userinfo`. Nothing in a tool call carries it, so the
provider's prepare step fetches it: that is what PREPARE is for, and it
is the same seam ClickUp uses to turn a list name into an id.

**There is no refresh token** for an ordinary app: LinkedIn issues those
to approved programs only. An access token lasts about 60 days and then
the person reconnects, which is why nothing here pretends to renew it.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import app_triage
import connections as C
import mytools
import oauth_providers as O
import oauth_refresh as F

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")

TOKEN_RESPONSE = {
    "access_token": "AQX...",
    "expires_in": 5184000,
    "scope": "openid,profile,email,w_member_social",
    "token_type": "Bearer",
    "id_token": "ey...",
}

USERINFO = {"sub": "8675309", "name": "Ralph Benitez",
            "email": "me@example.com", "email_verified": True}


def _tool(name):
    for t in mytools.PROVIDER_TOOLS["linkedin"]:
        if t.name == name:
            return t
    raise AssertionError("no such linkedin tool: " + name)


# --- the credential -------------------------------------------------------

def test_linkedin_is_a_provider_with_no_paste_form():
    p = C.provider("linkedin")
    assert p is not None
    assert p.fields == [], "there is no LinkedIn credential to paste"
    assert O.supports_oauth("linkedin") is True


def test_every_request_carries_the_protocol_header_linkedin_demands():
    """Their docs: "All requests require the following header:
    X-Restli-Protocol-Version: 2.0.0"."""
    auth = C.vendor_auth("linkedin", {"token": "tok"})
    assert auth.base_url == "https://api.linkedin.com/v2"
    assert auth.headers["Authorization"] == "Bearer tok"
    assert auth.headers["X-Restli-Protocol-Version"] == "2.0.0"


def test_the_probe_is_the_openid_userinfo_endpoint():
    assert C.provider("linkedin").probe_path == "/userinfo"
    assert C.provider("linkedin").probe_method == "GET"


def test_the_card_is_named_after_the_person():
    assert C.account_label("linkedin", USERINFO) == "Ralph Benitez"
    assert C.account_label("linkedin", {"email": "me@example.com"}) \
        == "me@example.com"


# --- the OAuth entry ------------------------------------------------------

def test_the_endpoints_are_linkedins_own():
    p = O.PROVIDERS["linkedin"]
    assert p.authorize_endpoint == \
        "https://www.linkedin.com/oauth/v2/authorization"
    assert p.token_endpoint == "https://www.linkedin.com/oauth/v2/accessToken"


def test_the_scope_is_the_four_that_need_no_approval():
    """Asking for one more would make this a partner application nobody
    has approved, and the authorize URL would simply refuse."""
    assert set(O.LINKEDIN_SCOPE.split()) == {
        "openid", "profile", "email", "w_member_social"}


def test_nothing_pretends_the_token_can_be_renewed():
    """LinkedIn issues refresh tokens to approved programs only, so an
    ordinary app gets none. Sixty days, then reconnect, and the card says
    so rather than a renewal failing in the background."""
    values, label = O.read_token_response("linkedin", TOKEN_RESPONSE)
    assert "refresh_token" not in values
    assert F.refreshable("linkedin", values) is False
    assert float(values["expires_at"]) > 0
    assert label == ""


def test_the_id_token_is_not_stored():
    """It is a signed claim about who signed in, not a credential for
    calling anything, and it is the longest string in the response."""
    values, _ = O.read_token_response("linkedin", TOKEN_RESPONSE)
    assert "id_token" not in values
    assert TOKEN_RESPONSE["id_token"] not in str(values)


# --- the author URN, which no tool call carries --------------------------

def test_the_person_urn_is_fetched_and_shaped():
    async def get(path, extra=None):
        assert path == "/userinfo", path
        return USERINFO

    import asyncio
    args, problem = asyncio.run(
        mytools._linkedin_prepare("create_post", {"text": "hello"}, get))
    assert problem is None
    assert args["author"] == "urn:li:person:8675309"


def test_a_lookup_that_failed_refuses_rather_than_posting_without_an_author():
    """A share with no author is a 400 after the model has already been
    told the post went out. Better to say the credential needs
    reconnecting."""
    async def get(path, extra=None):
        return None

    import asyncio
    args, problem = asyncio.run(
        mytools._linkedin_prepare("create_post", {"text": "hi"}, get))
    assert problem and "reconnect" in problem.lower()


def test_an_author_passed_in_is_not_looked_up_again():
    calls = []

    async def get(path, extra=None):
        calls.append(path)
        return USERINFO

    import asyncio
    args, problem = asyncio.run(mytools._linkedin_prepare(
        "create_post", {"text": "hi", "author": "urn:li:person:1"}, get))
    assert calls == []
    assert args["author"] == "urn:li:person:1"


def test_whoami_needs_no_lookup_of_its_own():
    calls = []

    async def get(path, extra=None):
        calls.append(path)
        return USERINFO

    import asyncio
    asyncio.run(mytools._linkedin_prepare("whoami", {}, get))
    assert calls == []


# --- the share body ------------------------------------------------------

def test_a_text_share_is_the_shape_linkedin_documents():
    body = mytools._linkedin_post_body(
        {"author": "urn:li:person:8675309", "text": "Hello World!"})
    assert body["author"] == "urn:li:person:8675309"
    assert body["lifecycleState"] == "PUBLISHED"
    content = body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert content["shareCommentary"]["text"] == "Hello World!"
    assert content["shareMediaCategory"] == "NONE"
    assert body["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"] \
        == "PUBLIC"


def test_a_link_share_carries_the_url_as_media():
    body = mytools._linkedin_post_body(
        {"author": "urn:li:person:1", "text": "Worth a read",
         "url": "https://example.com/post", "title": "A post"})
    content = body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert content["shareMediaCategory"] == "ARTICLE"
    media = content["media"][0]
    assert media["status"] == "READY"
    assert media["originalUrl"] == "https://example.com/post"
    assert media["title"]["text"] == "A post"


def test_a_post_can_be_kept_to_connections():
    body = mytools._linkedin_post_body(
        {"author": "urn:li:person:1", "text": "x", "audience": "connections"})
    assert body["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"] \
        == "CONNECTIONS"


def test_anything_but_connections_means_public():
    """A typo must not quietly narrow the audience of a post somebody
    meant to be public, and must not widen one either: only the exact
    word narrows it."""
    for given in ("public", "PUBLIC", "everyone", "", None, "conections"):
        body = mytools._linkedin_post_body(
            {"author": "urn:li:person:1", "text": "x", "audience": given})
        assert body["visibility"][
            "com.linkedin.ugc.MemberNetworkVisibility"] == "PUBLIC", given


def test_a_post_with_no_words_is_not_sent():
    assert mytools._linkedin_post_body(
        {"author": "urn:li:person:1", "text": "   "}) == {}


# --- the tools -----------------------------------------------------------

def test_there_is_one_read_and_one_write():
    names = {t.name for t in mytools.PROVIDER_TOOLS["linkedin"]}
    assert names == {"whoami", "create_post"}


def test_posting_is_a_write_and_says_so_plainly():
    t = _tool("create_post")
    assert t.method == "POST" and t.path == "/ugcPosts"
    assert mytools._writes(t) is True
    said = t.summary.lower()
    assert "public" in said, (
        "a tool that publishes under somebody's professional name has to "
        "say so in the sentence a model reads: " + t.summary)


def test_reading_who_you_are_is_not_a_write():
    assert mytools._writes(_tool("whoami")) is False


# --- the rest of the wiring ---------------------------------------------

def test_the_panel_offers_linkedin_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'linkedin'" in l]
    assert line and "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_linkedin_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-linkedin"' in src
    assert 'MCP_MYTOOLS_URL + "/linkedin"' in src


def test_the_triage_agent_knows_what_it_is_for_and_what_it_cannot_do():
    app = app_triage.APPS.get("linkedin")
    assert app is not None
    assert "post" in app.can.lower()
    cannot = app.cannot.lower()
    for shut in ("feed", "connections", "company"):
        assert shut in cannot, shut
    assert set(app.tools) <= {t.name
                              for t in mytools.PROVIDER_TOOLS["linkedin"]}
