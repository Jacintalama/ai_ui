"""Todoist connects by approving, not by pasting a token.

The paste form shipped first (PR #271) and still works. This puts a button
in front of it once a Todoist app is registered and its client id and secret
are on the server. Until then `configured()` is False and the card keeps the
form, so nothing changes for anybody the day this deploys.

Read off Todoist's own API v1 docs on 2026-11-23, not guessed:

  - authorize at app.todoist.com/oauth/authorize, exchange at
    api.todoist.com/oauth/access_token, two different hosts;
  - the client id and secret go in the body, as `-d` fields;
  - `scope` is a COMMA separated list, where every other vendor here uses
    spaces;
  - a token from a new app dies in 3600 seconds and comes with a refresh
    token that ROTATES on every renewal, so the one in each answer has to
    replace the stored one or the next renewal has nothing valid to send.
"""
from urllib.parse import parse_qs, urlsplit

import connections as C
import oauth_providers as O
import oauth_refresh as F


TOKEN_RESPONSE = {
    "access_token": "tdat_1",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "tdrt_1",
    "scope": "data:read_write",
}


def _params(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --- the provider entry ---------------------------------------------------

def test_todoist_can_be_connected_by_approving():
    assert O.supports_oauth("todoist") is True
    assert O.one_click("todoist") is True


def test_the_endpoints_are_the_ones_todoist_documents():
    p = O.PROVIDERS["todoist"]
    assert p.authorize_endpoint == "https://app.todoist.com/oauth/authorize"
    assert p.token_endpoint == "https://api.todoist.com/oauth/access_token"


def test_the_button_stays_off_until_both_keys_are_on_the_server(monkeypatch):
    monkeypatch.setattr(O, "_env", lambda name, default="": "")
    assert O.configured("todoist") is False
    keys = {"TODOIST_CLIENT_ID": "cid"}
    monkeypatch.setattr(O, "_env", lambda name, default="": keys.get(name, ""))
    assert O.configured("todoist") is False, "half configured is off"
    keys["TODOIST_CLIENT_SECRET"] = "sec"
    assert O.configured("todoist") is True


# --- the authorize URL ----------------------------------------------------

def test_the_authorize_url_carries_what_todoist_requires():
    url = O.authorize_url("todoist", "cid-1", "https://io.example/cb", "st-1")
    assert url.startswith("https://app.todoist.com/oauth/authorize?")
    q = _params(url)
    assert q["client_id"] == "cid-1"
    assert q["state"] == "st-1"
    assert q["redirect_uri"] == "https://io.example/cb"
    assert q["response_type"] == "code"
    assert q["scope"] == O.TODOIST_SCOPE


def test_the_scope_reads_and_writes_but_never_deletes():
    """Every Todoist tool reads or writes; none deletes. `data:read_write`
    already includes `task:add` and `data:read`, and `data:delete` /
    `project:delete` are left off because nothing here would use them."""
    asked = set(O.TODOIST_SCOPE.split(","))
    assert asked == {"data:read_write"}
    assert "delete" not in O.TODOIST_SCOPE


def test_no_pkce_reaches_todoist():
    """The console-app flow documents none; PKCE is only for Todoist's
    metadata-document clients."""
    assert O.PROVIDERS["todoist"].pkce is False
    url = O.authorize_url("todoist", "c", "https://io.example/cb", "s",
                          verifier="never-send-me")
    assert "code_challenge" not in url and "never-send-me" not in url


# --- how the client authenticates ----------------------------------------

def test_the_client_credentials_go_in_a_form_body():
    assert O.client_in_body("todoist") is True
    assert O.basic_header("todoist") == {}
    assert O.PROVIDERS["todoist"].token_body == "form"


# --- reading the token response ------------------------------------------

def test_the_token_and_its_renewal_both_survive_the_exchange():
    values, label = O.read_token_response("todoist", TOKEN_RESPONSE)
    assert values["token"] == "tdat_1"
    assert values["refresh_token"] == "tdrt_1"
    assert values["expires_at"] > 0
    assert label == "", "the route asks Todoist who this is, which proves it"


def test_an_answer_with_no_token_is_refused():
    import pytest
    with pytest.raises(ValueError):
        O.read_token_response("todoist", {"error": "bad_authorization_code"})


def test_the_stored_credential_is_sent_as_bearer_like_a_pasted_one():
    """The tools already send `Bearer <token>` for a pasted token; an OAuth
    token is the same header, so no tool changes."""
    values, _ = O.read_token_response("todoist", TOKEN_RESPONSE)
    auth = C.vendor_auth("todoist", values)
    assert auth.headers["Authorization"] == "Bearer tdat_1"


# --- renewal ----------------------------------------------------------------

def test_a_todoist_token_can_be_renewed(monkeypatch):
    monkeypatch.setattr(O, "_env", lambda name, default="": {
        "TODOIST_CLIENT_ID": "cid", "TODOIST_CLIENT_SECRET": "sec"}.get(name, ""))
    values, _ = O.read_token_response("todoist", TOKEN_RESPONSE)
    assert F.refreshable("todoist", values) is True
    post = F.refresh_post("todoist", values)
    assert post["url"] == "https://api.todoist.com/oauth/access_token"
    assert post["data"] == {"grant_type": "refresh_token",
                            "refresh_token": "tdrt_1",
                            "client_id": "cid", "client_secret": "sec"}


def test_the_rotated_refresh_token_replaces_the_old_one():
    """Todoist spends a refresh token on use. Keeping the old one would make
    the second renewal fail, and reusing it late revokes every token."""
    values, _ = O.read_token_response("todoist", TOKEN_RESPONSE)
    renewed = F.after_refresh(values, {"access_token": "tdat_2",
                                       "refresh_token": "tdrt_2",
                                       "expires_in": 3600})
    assert renewed["token"] == "tdat_2"
    assert renewed["refresh_token"] == "tdrt_2"
