"""Connecting GitHub and ClickUp by approving instead of pasting a token.

Both are ordinary OAuth 2.0 code exchanges, so unlike Trello they needed no
new flow: one PROVIDERS entry each. What they did need was three details
checked against each vendor's own documentation rather than assumed, because
every one of them fails silently or confusingly:

  GitHub answers the token request in `key=value&key=value` unless the
  request carries `Accept: application/json`, and this service reads every
  token response with r.json().

  GitHub and ClickUp both answer 200 with an error body when a code is spent
  or wrong, so a 4xx check alone would store an empty credential and show a
  card saying Connected.

  ClickUp takes the same token two different ways: a personal token raw, an
  OAuth token as `Bearer <token>`. One widely copied third-party guide says
  Bearer is never used, which is wrong for OAuth and would 401 every call.

Neither token response names the account, so the label is left empty here and
the route asks the vendor who this is, which verifies the token at the same
time.

HubSpot and Airtable are deliberately absent and there is a test for that
below. 2026-10-30.
"""
import pytest

import connections as C
import oauth_providers as O


# --- both are real OAuth 2.0, which Trello is not ----------------------------

def test_github_and_clickup_are_one_click_and_oauth2():
    for pid in ("github", "clickup"):
        assert O.one_click(pid) is True
        assert O.supports_oauth(pid) is True


def test_trello_is_still_one_click_without_being_oauth2():
    """The two kinds must not blur together: pointing the code exchange at a
    vendor that has none is the mistake this guards."""
    assert O.one_click("trello") is True
    assert O.supports_oauth("trello") is False


def test_notion_was_left_alone():
    assert O.supports_oauth("notion") is True
    assert O.PROVIDERS["notion"].token_body == "json"
    assert O.PROVIDERS["notion"].token_auth == "basic"


# --- the vendors that must NOT be offered yet --------------------------------

def test_hubspot_and_airtable_are_not_offered_until_a_refresh_exists():
    """Both hand back a refresh_token and an access token that dies in under
    an hour, and nothing in this service refreshes anything. The button would
    work for half an hour and then stop, while the card still said Connected,
    and it would be replacing a paste-form token that never expires.

    So this is a downgrade, not a gap. Delete this test when refresh lands,
    not before.
    """
    for pid in sorted(O.NEEDS_TOKEN_REFRESH_FIRST):
        assert O.supports_oauth(pid) is False
        assert O.one_click(pid) is False
        assert pid not in O.PROVIDERS


def test_the_ones_that_will_never_offer_it_still_do_not():
    """n8n is the user's own server and Zapier's Catch Hook is a webhook
    rather than a grant."""
    for never in ("n8n", "zapier"):
        assert O.one_click(never) is False


# --- it degrades to the paste form -------------------------------------------

@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_without_credentials_the_paste_form_stays(monkeypatch, pid):
    """A Connect button that strands somebody on a vendor error page is worse
    than a form that works."""
    stem = pid.upper()
    monkeypatch.delenv(stem + "_CLIENT_ID", raising=False)
    monkeypatch.delenv(stem + "_CLIENT_SECRET", raising=False)
    assert O.configured(pid) is False


@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_half_configured_counts_as_off(monkeypatch, pid):
    """An id with no secret cannot complete an exchange."""
    stem = pid.upper()
    monkeypatch.setenv(stem + "_CLIENT_ID", "cid")
    monkeypatch.delenv(stem + "_CLIENT_SECRET", raising=False)
    assert O.configured(pid) is False
    monkeypatch.setenv(stem + "_CLIENT_SECRET", "csec")
    assert O.configured(pid) is True


# --- where the browser is sent -----------------------------------------------

def test_github_asks_for_the_scopes_it_needs():
    """`repo` because an automation that cannot open an issue or push is not
    worth connecting, and an OAuth app has no narrower repository scope.
    `read:user` is what makes the login readable for the card."""
    url = O.authorize_url("github", client_id="CID",
                          redirect_uri="https://io.example/cb", state="S")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "repo" in O.GITHUB_SCOPE
    assert "read%3Auser" in url


def test_clickup_authorize_and_token_are_on_different_hosts():
    """Not a typo to be tidied away later: the consent page really is on
    app.clickup.com while the exchange is on api.clickup.com."""
    prov = O.PROVIDERS["clickup"]
    assert prov.authorize_endpoint == "https://app.clickup.com/api"
    assert prov.token_endpoint == "https://api.clickup.com/api/v2/oauth/token"


def test_clickup_asks_for_no_scopes():
    """ClickUp asks the person which Workspaces to authorize instead."""
    assert O.PROVIDERS["clickup"].authorize_extra == {}


@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_the_state_rides_along(pid):
    """Without it the callback cannot tell whose grant this is, and anyone
    who can make a signed-in browser follow the callback could attach their
    own account to somebody else's user."""
    url = O.authorize_url(pid, client_id="CID",
                          redirect_uri="https://io.example/cb", state="S1")
    assert "state=S1" in url


# --- how the token request is encoded ----------------------------------------

def test_github_sends_a_form_not_json():
    """GitHub documents no content type for its token endpoint, so it gets
    the form encoding RFC 6749 specifies and its own examples send."""
    assert O.PROVIDERS["github"].token_body == "form"


def test_clickup_sends_json_as_its_reference_documents():
    assert O.PROVIDERS["clickup"].token_body == "json"


@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_neither_uses_http_basic(pid):
    """Notion wants Basic. These two want the id and secret in the body, and
    sending Basic instead is a rejected exchange with nothing to explain it."""
    assert O.PROVIDERS[pid].token_auth == "body"


# --- reading the token response ----------------------------------------------

@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_a_token_is_read(pid):
    values, _ = O.read_token_response(pid, {"access_token": "tok_1"})
    assert values["token"] == "tok_1"


@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_an_error_body_with_a_200_is_still_a_failure(pid):
    """Both vendors answer 200 and an error body for a spent or wrong code.
    Without this the stored credential would be empty and the card would say
    Connected."""
    with pytest.raises(ValueError):
        O.read_token_response(pid, {"error": "bad_verification_code"})
    with pytest.raises(ValueError):
        O.read_token_response(pid, {})
    with pytest.raises(ValueError):
        O.read_token_response(pid, {"access_token": ""})


@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_neither_can_name_the_account_so_neither_pretends_to(pid):
    """The label is empty on purpose. The route asks the vendor, which names
    the account AND proves the token works before a card claims anything."""
    _, label = O.read_token_response(pid, {"access_token": "tok_1"})
    assert label == ""


# --- ClickUp's two header shapes ---------------------------------------------

def test_a_pasted_clickup_token_is_still_sent_raw():
    """Every ClickUp connection that existed before one-click is a personal
    token with no scheme recorded, and raw is what those need."""
    auth = C.PROVIDERS["clickup"].build_auth({"token": "pk_123"})
    assert auth.headers["Authorization"] == "pk_123"


def test_a_clickup_oauth_token_is_sent_as_a_bearer():
    """Raw, an OAuth access token is a 401 on every call."""
    values, _ = O.read_token_response("clickup", {"access_token": "cu_abc"})
    auth = C.PROVIDERS["clickup"].build_auth(values)
    assert auth.headers["Authorization"] == "Bearer cu_abc"


def test_the_clickup_scheme_is_recorded_by_the_connect_not_guessed():
    """A prefix test on the token's shape would be a guess that breaks the
    day either vendor changes its token format."""
    values, _ = O.read_token_response("clickup", {"access_token": "cu_abc"})
    assert values.get("scheme") == "Bearer"


def test_github_sends_a_bearer_either_way():
    """GitHub accepts a Bearer for both an OAuth token and a personal access
    token, so it needs no scheme recorded and the paste form is unaffected."""
    values, _ = O.read_token_response("github", {"access_token": "gho_1"})
    assert "scheme" not in values
    auth = C.PROVIDERS["github"].build_auth(values)
    assert auth.headers["Authorization"] == "Bearer gho_1"


# --- the card can still connect them the old way -----------------------------

@pytest.mark.parametrize("pid", ["github", "clickup"])
def test_the_paste_form_is_untouched(pid):
    """One-click is an addition. A deployment with no app registered, and
    anyone who would rather paste a token, both keep what they had."""
    assert C.required_fields(pid) == ["token"]
