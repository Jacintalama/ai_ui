"""Connecting Trello in one click.

Before this a person opened trello.com/power-ups/admin, made a Power-Up to
get an API key, copied it, clicked a Token link and copied that too. Four
steps and two pastes, and where somebody who is not a developer gives up.
Asked for on 2026-10-30, for automations: a rule that watches a board is
worth nothing if nobody gets as far as connecting the board.

**Trello has no OAuth 2.0.** Checked against Atlassian's docs rather than
assumed. It has its `1/authorize` flow and OAuth 1.0a, and that is all, so
it cannot use oauth_providers.py, which is a code exchange and only that.
RFC-89 proposed OAuth 2.0 and nothing confirms it shipped.

The token comes back in the URL FRAGMENT, which no server ever receives, so
a page reads it in the browser and posts it back. That is Trello's design,
not a workaround we chose, and it is the part most worth pinning.
"""
import os

import pytest

import trello_connect as T

KEY = "a" * 32
TOKEN = "b" * 64
BACK = "https://io.example.com/api/tasks/connections/trello/oauth/callback?state=s1"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(T.ENV_KEY, KEY)
    return KEY


# --- the button is only offered when it can work -------------------------------

def test_without_a_key_there_is_no_one_click(monkeypatch):
    """The paste form has to stay. Offering the button would send somebody to
    a Trello page that refuses them."""
    monkeypatch.delenv(T.ENV_KEY, raising=False)
    assert T.configured() is False


def test_with_a_key_there_is(configured):
    assert T.configured() is True


def test_a_blank_key_is_not_a_key(monkeypatch):
    monkeypatch.setenv(T.ENV_KEY, "   ")
    assert T.configured() is False


# --- what the person is sent to ------------------------------------------------

def test_the_authorize_url_carries_our_key_not_theirs(configured):
    url = T.authorize_url(BACK)
    assert url.startswith("https://trello.com/1/authorize?")
    assert "key=" + KEY in url


def test_it_asks_for_read_and_write(configured):
    """An automation that can only read cannot move a card or add a comment,
    which is most of what anyone asks for. Trello shows the person this."""
    assert "scope=read%2Cwrite" in T.authorize_url(BACK)


def test_the_token_is_asked_to_expire(configured):
    """Trello offers "never". A token that cannot expire is one nobody can
    keep track of."""
    url = T.authorize_url(BACK)
    assert "expiration=30days" in url
    assert "expiration=never" not in url


def test_the_return_url_is_carried_whole(configured):
    """The state rides in its query string, and losing it would mean a token
    arriving with nobody to attach it to."""
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(T.authorize_url(BACK)).query)
    assert q["return_url"][0] == BACK


def test_the_app_is_named_so_the_person_knows_who_is_asking(configured):
    assert "name=" + T.APP_NAME in T.authorize_url(BACK)


# --- reading the token out of the fragment -------------------------------------

def test_the_usual_shape_is_read():
    assert T.token_from_fragment("#token=" + TOKEN) == TOKEN


def test_a_bare_fragment_is_read_too():
    """Trello has sent both over the years, and a reader of this code should
    not have to find that out from a failure in production."""
    assert T.token_from_fragment("#" + TOKEN) == TOKEN


def test_no_fragment_is_no_token():
    for empty in ["", "#", "   ", None]:
        assert T.token_from_fragment(empty) == ""


def test_an_error_fragment_yields_no_token():
    assert T.token_from_fragment("#error=access_denied") == ""


# --- why Trello sent somebody back empty handed ------------------------------

def test_trellos_reason_is_read_out_of_the_fragment():
    """Trello puts `token=` empty and `error=<message>` in the fragment when
    it refuses. Reading only the token turned every refusal into the same
    blank sentence and threw away the one account of what went wrong."""
    frag = "#token=&error=invalid+scope+requested"
    assert T.token_from_fragment(frag) == ""
    assert T.error_from_fragment(frag) == "invalid scope requested"


def test_a_good_fragment_carries_no_reason():
    """A success must not be described as a refusal."""
    assert T.error_from_fragment("#token=" + TOKEN) == ""
    assert T.error_from_fragment("#" + TOKEN) == ""


def test_nothing_back_means_no_reason_rather_than_a_wrong_one():
    for empty in ["", "#", "   ", None]:
        assert T.error_from_fragment(empty) == ""


def test_a_reason_is_cut_to_a_sentence():
    """It is rendered on our page. Trello's messages are a sentence, so
    anything page-length is not a message and is not shown like one."""
    frag = "#token=&error=" + ("x" * 900)
    assert len(T.error_from_fragment(frag)) == T.MAX_REASON


def test_control_characters_never_reach_the_page():
    """The page writes this with textContent, so this is tidiness rather
    than the thing standing between us and an injection. It still should
    not be able to rewrite the line it sits on."""
    frag = "#token=&error=denied%0A%0D%00stop"
    assert T.error_from_fragment(frag) == "deniedstop"


# --- saying what came back, without saying what it was -----------------------

def test_an_empty_fragment_is_named_as_such():
    """Trello sending nothing and Trello sending a refusal are different
    problems, and they used to wear the same sentence."""
    assert "empty" in T.describe_fragment("")
    assert "empty" in T.describe_fragment("#")


def test_the_keys_are_named_and_the_values_are_not():
    """The whole point. A log line that helps, that cannot leak a token."""
    d = T.describe_fragment("#token=" + TOKEN + "&error=")
    assert "token[64 chars]" in d
    assert "error[0 chars]" in d
    assert TOKEN not in d


def test_a_bare_value_is_measured_not_quoted():
    d = T.describe_fragment("#" + TOKEN)
    assert "64 chars" in d
    assert "hex=True" in d
    assert TOKEN not in d


def test_rubbish_is_described_without_being_repeated():
    """An error page in the fragment must not end up in the log."""
    d = T.describe_fragment("#<!doctype html><title>Oops")
    assert "<title>" not in d
    assert "Oops" not in d


def test_no_description_ever_contains_the_token():
    """The one property that matters, over every shape we have seen."""
    for frag in ["#token=" + TOKEN, "#" + TOKEN,
                 "#token=" + TOKEN + "&error=nope", "#token=&error=nope"]:
        assert TOKEN not in T.describe_fragment(frag)


# --- what is allowed to be spent as a credential -------------------------------

def test_a_real_token_passes():
    assert T.looks_like_token(TOKEN) is True


def test_an_error_page_is_not_a_token():
    """The fragment is whatever the browser found. Without this, a chunk of
    HTML would be sent to Trello and stored as a credential."""
    assert T.looks_like_token("<!doctype html><title>Oops") is False


def test_something_too_short_or_too_long_is_not_a_token():
    assert T.looks_like_token("abc") is False
    assert T.looks_like_token("a" * 400) is False


#: What Trello's current admin issues: an Atlassian-shaped token, mixed case
#: and 76 characters, not the 64 hexadecimal ones every older app got.
ATLASSIAN_TOKEN = "ATTA" + ("aB3" * 24)


def test_the_token_trello_actually_sends_is_accepted():
    """The bug, pinned. This was measured in production on 2026-10-30: a
    76 character token arrived, was refused for not being hexadecimal, and
    the page told the person Trello had not returned a token.

    Both shapes have to pass. Apps registered years ago still issue hex, and
    a connection made under one must not break because the other exists.
    """
    assert len(ATLASSIAN_TOKEN) == 76
    assert T.looks_like_token(ATLASSIAN_TOKEN) is True
    assert T.looks_like_token(TOKEN) is True


def test_hex_is_not_the_rule_and_never_should_have_been():
    """This file used to assert the opposite, and that assertion was the
    bug wearing a passing test. A validator cannot tell a good token from a
    bad one; the call to /members/me that follows is what proves it."""
    assert T.looks_like_token("z" * 64) is True


def test_an_atlassian_tokens_punctuation_is_allowed():
    """These carry a checksum on the end and are not plain alphanumeric."""
    assert T.looks_like_token("ATATT" + "x" * 60 + "=A1B2C3D4") is True


def test_a_ceiling_that_is_not_the_next_thing_to_break():
    """76 today. The limit should not be the reason the next format fails."""
    assert T.looks_like_token("a" * T.MAX_TOKEN) is True
    assert T.looks_like_token("a" * (T.MAX_TOKEN + 1)) is False


def test_anything_with_a_space_in_it_is_not_a_credential():
    """What actually keeps a page out: no token has ever had whitespace in
    it, and no document has ever been without it."""
    assert T.looks_like_token("not a token but long enough to be one ok") is False
    assert T.looks_like_token(TOKEN[:32] + chr(10) + TOKEN[:32]) is False


def test_nothing_is_not_a_token():
    assert T.looks_like_token("") is False
    assert T.looks_like_token(None) is False


# --- what gets stored ----------------------------------------------------------

def test_the_stored_credential_keeps_the_shape_trello_already_wanted(configured):
    """Trello wants a key AND a token on every call, which is already what
    connections._trello_auth sends. Only where the key comes from changed, so
    every Trello tool and the verification keep working untouched."""
    values = T.stored_values(TOKEN)
    assert values == {"api_key": KEY, "token": TOKEN}


def test_the_key_is_stored_beside_the_token_not_read_later(configured,
                                                           monkeypatch):
    """A connection should keep working exactly as it was approved. If the
    deployment rotates its key, existing connections must not silently start
    sending a different one."""
    values = T.stored_values(TOKEN)
    monkeypatch.setenv(T.ENV_KEY, "f" * 32)
    assert values["api_key"] == KEY


# --- which key this uses, and which it must not --------------------------------

def test_the_connect_key_is_not_the_shared_platform_key():
    """mcp-trello pairs TRELLO_API_KEY with TRELLO_API_TOKEN as one
    platform-wide Trello account. A Trello token is bound to the key that
    issued it, so pointing TRELLO_API_KEY at a second app 401s that pair and
    every shared Trello tool with it.

    Measured on 2026-10-30 against Trello, not assumed: old key with the old
    token answered 200, the new key with the same token answered
    "invalid key". This is the whole reason for a separate name, and it reads
    like an inconsistency worth tidying away, so it is pinned here.
    """
    assert T.ENV_KEY == "TRELLO_CONNECT_KEY"
    assert T.ENV_KEY != "TRELLO_API_KEY"


def test_the_connect_key_is_read_from_its_own_name(monkeypatch):
    """Reading the shared key as a fallback would reintroduce exactly the
    mismatch above, quietly and only in production."""
    monkeypatch.setenv("TRELLO_API_KEY", "d" * 32)
    monkeypatch.delenv("TRELLO_CONNECT_KEY", raising=False)
    assert T.configured() is False
    assert T.api_key() == ""


# --- the shape of the thing ----------------------------------------------------

def test_trello_is_declared_as_one_click_but_not_oauth2():
    """Both halves matter. The card must offer the button, and the OAuth 2.0
    code exchange must never be pointed at a vendor that has none."""
    import oauth_providers as O
    assert O.one_click("trello") is True
    assert O.supports_oauth("trello") is False
    assert "trello" not in O.PROVIDERS


def test_notion_is_still_oauth2():
    import oauth_providers as O
    assert O.supports_oauth("notion") is True
    assert O.one_click("notion") is True


def test_the_apps_that_will_never_offer_it_still_do_not():
    """n8n is the user's own server and Zapier's Catch Hook is a webhook, not
    a grant. A card must not imply otherwise."""
    import oauth_providers as O
    for never in ("n8n", "zapier"):
        assert O.one_click(never) is False
        assert O.supports_oauth(never) is False
