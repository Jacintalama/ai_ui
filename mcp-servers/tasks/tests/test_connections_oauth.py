"""Connecting by approving, instead of by pasting a token.

Eight connectors shipped and nobody connected one in two days. The likeliest
reason is the ask: "go dig a personal access token out of a vendor's settings
page" is real work, and for Notion it is the most buried of the lot. OAuth
removes it: click, approve, done.

The parts worth testing are the parts that are security, not plumbing.

The `state` is a CSRF token bound to one user and spendable once. Without that
binding, anyone who can make the signed-in browser follow a callback URL can
attach THEIR account to YOUR user, which is account grafting, not a login bug.

The authorization URL is built from a fixed vendor host, and the callback
refuses a `code` it cannot tie to a state it issued.

And it degrades: until a deployment registers a developer app and sets the
client id and secret, the card must keep offering the paste-a-token form it has
today rather than showing a Connect button that goes nowhere. That is the same
fallback the Vercel connect already uses.
"""
import time

import pytest

import oauth_providers as O


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store():
    s = O.StateStore()
    yield s
    s.clear()


# --- the state is a real CSRF token ---------------------------------------

def test_a_state_is_bound_to_the_user_who_started_the_flow(store):
    s = store.mint("ralph@example.com")
    assert store.consume(s) == "ralph@example.com"


def test_a_state_can_only_be_spent_once(store):
    """A replayed callback must not attach the same grant twice, and a leaked
    URL in a history or a log must be inert the second time."""
    s = store.mint("ralph@example.com")
    assert store.consume(s) == "ralph@example.com"
    assert store.consume(s) is None


def test_a_state_nobody_issued_is_refused(store):
    assert store.consume("made-up-state") is None


@pytest.mark.parametrize("junk", ["", None, "   "])
def test_a_missing_state_is_refused(store, junk):
    assert store.consume(junk) is None


def test_a_state_expires(store):
    clock = _Clock()
    s = store.mint("ralph@example.com", now=clock())
    clock.t += O.STATE_TTL_SEC + 1
    assert store.consume(s, now=clock()) is None


def test_two_users_cannot_collide(store):
    a = store.mint("a@example.com")
    b = store.mint("b@example.com")
    assert a != b
    assert store.consume(b) == "b@example.com"
    assert store.consume(a) == "a@example.com"


def test_states_are_not_guessable(store):
    seen = {store.mint("ralph@example.com") for _ in range(50)}
    assert len(seen) == 50
    assert all(len(s) >= 20 for s in seen)


def test_expired_states_do_not_accumulate(store):
    """This lives in process memory. A flow that is started and abandoned must
    not leak an entry forever."""
    clock = _Clock()
    for _ in range(20):
        store.mint("ralph@example.com", now=clock())
    clock.t += O.STATE_TTL_SEC + 1
    store.mint("later@example.com", now=clock())
    assert store.size() == 1


# --- the authorization URL -------------------------------------------------

def test_notion_authorization_url_points_at_notion(store):
    url = O.authorize_url("notion", client_id="cid",
                          redirect_uri="https://example.test/cb", state="st")
    assert url.startswith("https://api.notion.com/v1/oauth/authorize")
    assert "client_id=cid" in url
    assert "state=st" in url
    assert "response_type=code" in url


def test_the_redirect_uri_is_carried_in_the_url(store):
    url = O.authorize_url("notion", client_id="cid",
                          redirect_uri="https://example.test/cb?a=b", state="st")
    assert "example.test" in url
    assert " " not in url


def test_an_unknown_provider_has_no_authorization_url():
    with pytest.raises(ValueError):
        O.authorize_url("myspace", client_id="c", redirect_uri="r", state="s")


def test_a_provider_without_oauth_is_reported_as_such():
    """n8n is the user's own server and Zapier's hook is not a grant. Neither
    can ever offer this, and the card must not pretend otherwise."""
    assert O.supports_oauth("notion") is True
    assert O.supports_oauth("n8n") is False
    assert O.supports_oauth("zapier") is False


# --- reading the vendor's answer -------------------------------------------

def test_notion_token_response_yields_the_credential_and_a_label():
    creds, label = O.read_token_response("notion", {
        "access_token": "secret_abc", "workspace_name": "Ralph's Wiki",
        "bot_id": "b1"})
    assert creds == {"token": "secret_abc"}
    assert label == "Ralph's Wiki"


def test_a_response_with_no_token_is_refused():
    """A vendor error body is still JSON with a 200 in some flows. No token
    means no connection, rather than storing an empty credential."""
    with pytest.raises(ValueError):
        O.read_token_response("notion", {"error": "invalid_grant"})


def test_a_workspace_with_no_name_still_gets_a_label():
    _, label = O.read_token_response("notion", {"access_token": "t"})
    assert label.strip()


# --- degrading when nobody has registered an app --------------------------

def test_oauth_is_off_until_a_client_id_and_secret_exist(monkeypatch):
    monkeypatch.setattr(O, "_env", lambda k, d="": "")
    assert O.configured("notion") is False


def test_oauth_is_on_once_both_are_set(monkeypatch):
    monkeypatch.setattr(O, "_env",
                        lambda k, d="": "x" if "NOTION" in k else d)
    assert O.configured("notion") is True


def test_half_configured_counts_as_off(monkeypatch):
    """An id with no secret cannot complete an exchange. Offering the button
    would strand the user on the vendor's site."""
    monkeypatch.setattr(
        O, "_env", lambda k, d="": "x" if k.endswith("CLIENT_ID") else "")
    assert O.configured("notion") is False


# --- the popup page is markup, and the label is not ours -------------------

import routes_connections as R


def test_a_workspace_name_cannot_break_out_of_the_script_tag():
    """json.dumps escapes quotes and backslashes and NOT "<". A Notion
    workspace called "</script><script>..." would therefore close the block it
    was embedded in and run. The name comes from a third party and the page is
    served from our own origin."""
    hostile = "</script><script>alert(1)</script>"
    page = R._oauth_done(True, "Connected to " + hostile).body.decode()
    assert "</script><script>" not in page
    # exactly one real script block, the one we wrote
    assert page.count("<script>") == 1
    assert page.count("</script>") == 1


def test_a_hostile_name_is_still_shown_as_text():
    """Escaping must not silently drop the message."""
    page = R._oauth_done(False, "Nope <b>bold</b>").body.decode()
    assert "bold" in page


def test_the_label_notion_returns_is_stripped_of_brackets():
    """Belt and braces: bounded and de-tagged where it enters, as well as
    escaped where it is rendered."""
    _, label = O.read_token_response("notion", {
        "access_token": "t", "workspace_name": "<img src=x onerror=alert(1)>"})
    assert "<" not in label and ">" not in label


def test_the_page_is_valid_markup_with_no_placeholders_left():
    page = R._oauth_done(True, "fine").body.decode()
    assert "@" not in page
    assert page.startswith("<!doctype html>")


# --- the callback's USE of the state, not just the state itself ------------
# StateStore being correct proves nothing if oauth_callback ignores what it
# returns. Making the callback fall back to a hardcoded email passed every test
# above, which is precisely the account-grafting hole these tests exist for.

import asyncio


@pytest.fixture
def stored_grants(monkeypatch):
    """Capture what the callback tries to persist, without a database."""
    grants = []

    async def _fake_store(email, provider_id, values, label):
        grants.append({"email": email, "provider": provider_id,
                       "values": values, "label": label})

    monkeypatch.setattr(R, "_store_connection", _fake_store)

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "secret_from_vendor",
                    "workspace_name": "Someone Else's Wiki"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(R.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(O, "_env", lambda k, d="": "configured")
    return grants


def _call(provider="notion", **kw):
    return asyncio.run(R.oauth_callback(provider, **kw))


def test_a_callback_with_a_state_nobody_issued_stores_nothing(stored_grants):
    """The hole this guards: without it, anyone able to make a signed-in
    browser follow this URL attaches THEIR vendor account to the session's
    user."""
    page = _call(code="a-real-looking-code", state="forged").body.decode()
    assert stored_grants == []
    assert "expired" in page.lower()


def test_a_callback_with_no_state_at_all_stores_nothing(stored_grants):
    _call(code="a-real-looking-code", state="")
    assert stored_grants == []


def test_a_replayed_callback_only_grants_once(stored_grants):
    state = O.STATES.mint("ralph@example.com")
    _call(code="c1", state=state)
    _call(code="c1", state=state)
    assert len(stored_grants) == 1


def test_the_grant_lands_on_the_user_who_started_the_flow(stored_grants):
    state = O.STATES.mint("ralph@example.com")
    _call(code="c1", state=state)
    assert stored_grants[0]["email"] == "ralph@example.com"
    assert stored_grants[0]["values"] == {"token": "secret_from_vendor"}


def test_a_cancelled_authorization_stores_nothing(stored_grants):
    state = O.STATES.mint("ralph@example.com")
    _call(error="access_denied", state=state)
    assert stored_grants == []


def test_a_callback_with_no_code_stores_nothing(stored_grants):
    state = O.STATES.mint("ralph@example.com")
    _call(code="", state=state)
    assert stored_grants == []


def test_the_callback_never_echoes_the_code_or_the_token(stored_grants):
    state = O.STATES.mint("ralph@example.com")
    page = _call(code="SUPER_SECRET_CODE", state=state).body.decode()
    assert "SUPER_SECRET_CODE" not in page
    assert "secret_from_vendor" not in page
