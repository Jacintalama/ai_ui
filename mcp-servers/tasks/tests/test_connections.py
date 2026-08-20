"""Connecting your own account to a third-party tool.

Fifteen of the sixteen cards in the Connections dialog said "Coming soon"
because integrations-ui.js carried `real: true` on Google alone. Four of them
(ClickUp 172 tools, GitHub 40, Trello 25, n8n 20) had a working container and
an indexed tool list the whole time. What was missing was never the plumbing to
the vendor, it was anywhere to put YOUR credential: the containers take one
shared token from boot-time env, so using them means acting as the platform's
own account.

This module is the per-user half. What it pins down:

  - "Connected" is never asserted on the strength of a well-formed string. The
    credential is checked against the vendor's own API first, and the label
    shown on the card is the account name the vendor returned. A card that says
    Connected means someone at ClickUp confirmed the token.
  - A provider with two fields (Trello wants key AND token, n8n wants a base
    URL AND an api key) is refused with BOTH names when both are missing, not
    one at a time.
  - Secrets are never echoed. Not in a response, not in a log line, not in an
    error message.
"""
import json

import pytest

import connections as C


ALL = ["clickup", "trello", "github", "notion", "n8n"]


# --- the registry ---------------------------------------------------------

@pytest.mark.parametrize("pid", ALL)
def test_every_advertised_provider_is_registered(pid):
    assert C.provider(pid) is not None


def test_an_unknown_provider_is_not_invented():
    assert C.provider("myspace") is None
    assert C.provider("") is None


@pytest.mark.parametrize("pid", ALL)
def test_every_provider_declares_at_least_one_field(pid):
    assert C.required_fields(pid)


def test_the_two_field_providers_ask_for_both():
    """Trello signs with an API key AND a token; either alone is useless."""
    assert set(C.required_fields("trello")) == {"api_key", "token"}
    assert set(C.required_fields("n8n")) == {"base_url", "api_key"}


# --- refusing incomplete input --------------------------------------------

def test_missing_fields_are_all_reported_at_once():
    assert set(C.missing_fields("trello", {})) == {"api_key", "token"}


def test_a_half_filled_form_names_only_what_is_missing():
    assert C.missing_fields("trello", {"api_key": "k"}) == ["token"]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_whitespace_is_not_a_credential(blank):
    assert "token" in C.missing_fields("github", {"token": blank})


def test_a_complete_form_is_accepted():
    assert C.missing_fields("github", {"token": "ghp_x"}) == []


# --- the verification call ------------------------------------------------

def test_clickup_is_checked_against_clickups_own_api():
    req = C.verify_request("clickup", {"token": "pk_123"})
    assert req.url.startswith("https://api.clickup.com/")
    assert req.headers["Authorization"] == "pk_123"


def test_github_uses_a_bearer_token():
    req = C.verify_request("github", {"token": "ghp_abc"})
    assert req.url.startswith("https://api.github.com/")
    assert req.headers["Authorization"] == "Bearer ghp_abc"


def test_notion_sends_the_api_version_it_requires():
    """Notion rejects any request without Notion-Version. Leaving it off is how
    the existing mcp-notion container would fail even with a real key."""
    req = C.verify_request("notion", {"token": "secret_x"})
    assert req.headers["Notion-Version"]


def test_trello_signs_with_both_halves():
    req = C.verify_request("trello", {"api_key": "KEY", "token": "TOK"})
    assert req.params["key"] == "KEY" and req.params["token"] == "TOK"


def test_n8n_is_checked_against_the_users_own_host():
    """n8n is self-hosted, so there is no fixed vendor URL to check against."""
    req = C.verify_request("n8n", {"base_url": "https://n8n.example.com",
                                   "api_key": "K"})
    assert req.url.startswith("https://n8n.example.com/")
    assert req.headers["X-N8N-API-KEY"] == "K"


def test_a_trailing_slash_on_a_self_hosted_url_does_not_double_up():
    req = C.verify_request("n8n", {"base_url": "https://n8n.example.com/",
                                   "api_key": "K"})
    assert "//api" not in req.url.split("://", 1)[1]


@pytest.mark.parametrize("bad", ["ftp://x", "notaurl", "javascript:alert(1)"])
def test_a_self_hosted_url_must_be_http(bad):
    with pytest.raises(ValueError):
        C.verify_request("n8n", {"base_url": bad, "api_key": "K"})


# --- what the card ends up saying -----------------------------------------

def test_the_label_is_the_account_the_vendor_named():
    assert C.account_label("clickup", {"user": {"username": "ralph"}}) == "ralph"
    assert C.account_label("github", {"login": "thunder500"}) == "thunder500"
    assert C.account_label("trello", {"username": "ralphb"}) == "ralphb"
    assert C.account_label("notion", {"name": "Ralph B"}) == "Ralph B"


def test_a_vendor_that_names_nothing_still_gets_a_label():
    """Never blank: a card reading "Connected" with no account under it gives
    the user no way to tell WHICH account they connected."""
    for pid in ALL:
        assert C.account_label(pid, {}).strip()


def test_a_hostile_label_is_not_taken_at_face_value():
    """The label is rendered into the card. It comes from a third party."""
    got = C.account_label("github", {"login": "<img src=x onerror=alert(1)>"})
    assert "<" not in got and ">" not in got


def test_an_absurdly_long_label_is_cut():
    assert len(C.account_label("github", {"login": "x" * 5000})) <= 80


# --- secrets do not leak --------------------------------------------------

def test_redaction_hides_every_secret_field():
    red = C.redact("trello", {"api_key": "KEY123", "token": "TOK456"})
    assert "KEY123" not in json.dumps(red)
    assert "TOK456" not in json.dumps(red)


def test_redaction_keeps_the_non_secret_field_readable():
    """n8n's base_url is not a secret and is the thing you need to see to know
    which host you connected to."""
    red = C.redact("n8n", {"base_url": "https://n8n.example.com", "api_key": "K"})
    assert red["base_url"] == "https://n8n.example.com"
    assert "K" != red["api_key"]


@pytest.mark.parametrize("pid", ALL)
def test_no_provider_marks_a_credential_as_public(pid):
    p = C.provider(pid)
    assert any(f.secret for f in p.fields), pid


# --- the vendor auth shape, stated once -----------------------------------
# Verification and every per-user tool call have to sign the same way. Two
# copies of "how do you authenticate to Trello" is two chances to get it wrong
# and one chance to fix it, so the shape is declared once and reused.

def test_verification_and_tool_calls_share_one_auth_shape():
    creds = {"token": "pk_123"}
    auth = C.vendor_auth("clickup", creds)
    probe = C.verify_request("clickup", creds)
    assert probe.url.startswith(auth.base_url)
    for k, v in auth.headers.items():
        assert probe.headers[k] == v


@pytest.mark.parametrize("pid,creds", [
    ("clickup", {"token": "T"}),
    ("github", {"token": "T"}),
    ("notion", {"token": "T"}),
    ("trello", {"api_key": "K", "token": "T"}),
    ("n8n", {"base_url": "https://n8n.example.com", "api_key": "K"}),
])
def test_every_provider_can_sign_an_arbitrary_call(pid, creds):
    auth = C.vendor_auth(pid, creds)
    assert auth.base_url.startswith("http")
    assert auth.headers or auth.params


def test_a_self_hosted_base_url_is_the_users_own_host():
    auth = C.vendor_auth("n8n", {"base_url": "https://n8n.example.com/",
                                 "api_key": "K"})
    assert auth.base_url == "https://n8n.example.com"


def test_signing_without_a_credential_is_refused():
    """A tool call arriving for someone who never connected must not go out
    unsigned and get a confusing 401 from the vendor."""
    for pid in ALL:
        with pytest.raises(ValueError):
            C.vendor_auth(pid, {})


# --- the three added on 2026-08-20 ----------------------------------------

NEW = ["airtable", "hubspot", "zapier"]


@pytest.mark.parametrize("pid", NEW)
def test_the_new_providers_are_registered(pid):
    assert C.provider(pid) is not None


def test_asana_is_not_offered():
    """Pulled at Ralph's request. A card that cannot be connected is worse
    than no card."""
    assert C.provider("asana") is None


def test_airtable_uses_a_personal_access_token():
    req = C.verify_request("airtable", {"token": "patABC"})
    assert req.url.startswith("https://api.airtable.com/")
    assert req.headers["Authorization"] == "Bearer patABC"


def test_hubspot_uses_a_private_app_token():
    req = C.verify_request("hubspot", {"token": "pat-na1-xyz"})
    assert req.url.startswith("https://api.hubapi.com/")
    assert req.headers["Authorization"] == "Bearer pat-na1-xyz"


def test_zapier_is_checked_with_a_post_not_a_get():
    """A catch hook has nothing to read. The only way to know a webhook is
    live is to send it something, which is exactly what Zapier's own "test
    trigger" step does."""
    p = C.provider("zapier")
    assert p.probe_method == "POST"
    assert p.probe_body


@pytest.mark.parametrize("pid", ["airtable", "hubspot"])
def test_the_read_only_providers_are_checked_with_a_get(pid):
    assert C.provider(pid).probe_method == "GET"


def test_zapier_posts_to_the_users_own_hook(self_url="https://hooks.zapier.com/hooks/catch/123/abc/"):
    req = C.verify_request("zapier", {"webhook_url": self_url})
    assert req.url.startswith(self_url.rstrip("/"))


@pytest.mark.parametrize("bad", [
    "https://example.com/hooks/catch/1/a/",     # not Zapier
    "http://hooks.zapier.com/hooks/catch/1/a/",  # not https
    "https://hooks.zapier.com/",                 # not a catch hook
    "not a url",
])
def test_a_url_that_is_not_a_zapier_hook_is_refused(bad):
    """The URL is posted to, so it is a request this platform makes to an
    address the user supplied. It has to be a Zapier hook and nothing else."""
    with pytest.raises(ValueError):
        C.verify_request("zapier", {"webhook_url": bad})


def test_the_new_providers_label_the_account_they_reached():
    assert C.account_label("airtable", {"email": "ralph@example.com"}) == "ralph@example.com"
    assert C.account_label("airtable", {"id": "usr123"}) == "usr123"
    assert "12345" in C.account_label("hubspot", {"portalId": 12345})
    assert C.account_label("zapier", {"status": "success"}).strip()


@pytest.mark.parametrize("pid", NEW)
def test_the_new_providers_say_where_to_find_the_credential(pid):
    assert len(C.provider(pid).where) > 20
