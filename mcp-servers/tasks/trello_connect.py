"""Connecting Trello in one click (2026-10-30).

Before this, a person had to open trello.com/power-ups/admin, create a
Power-Up to get an API key, copy it, click a Token link beside it, and copy
that too. Four steps and two pastes, and the step where somebody who is not
a developer gives up. Automations are worth nothing if nobody gets as far as
connecting the app they want automated.

**Trello HAS OAuth 2.0, and this deliberately does not use it.** Corrected
2026-10-30: this file used to say Trello had none. That was true of
Atlassian's docs when it was written and is no longer true of Trello's app
admin, which now has an OAuth 2.0 tab issuing a client id and granular
scopes. Recorded rather than quietly edited, because a confident wrong note
in this repo has cost a wrong conclusion before.

It is still not used, for a better reason than the one originally given.
Trello's OAuth 2.0 access token expires in one hour and is renewed with a
ROTATING, single-use refresh token, and nothing in this service refreshes
anything. A connect that stops working after an hour, while the card still
says Connected, is worse than one that lasts thirty days. Trello therefore
sits with HubSpot and Airtable in oauth_providers.NEEDS_TOKEN_REFRESH_FIRST
territory, except that unlike those two it has a working route that needs no
refresh at all, which is the one below.

`1/authorize` is not deprecated. Atlassian's authorization guide still
presents it as a current option, alongside OAuth 1.0a.

`1/authorize` is the route Trello's own guide calls the simpler one. The
shape:

    we send the browser to trello.com/1/authorize?key=OURS&return_url=...
    the person approves
    Trello sends them back with the token in the URL FRAGMENT

A fragment never reaches a server, so the return_url serves a page that
reads it in the browser and posts it back here. That is the only part of
this that is unusual, and it is Trello's design, not ours.

What makes this small: the stored credential does not change shape. Trello
wants a key and a token on every API call, which is already what
connections._trello_auth sends. The only difference is where the key comes
from. The person used to supply it; now the platform does, and they supply
nothing. Every Trello tool, the verification against /members/me and the
encryption are untouched.

The platform's API key is not a secret. Atlassian's API introduction says it
is "intended to be publicly accessible" and grants no access on its own: it
names the app, and the user's token is what carries the permission. So this
needs ONE value in the environment and no client secret, unlike GitHub or
ClickUp.
"""
from __future__ import annotations

import logging
import os
import urllib.parse

logger = logging.getLogger("trello_connect")

PROVIDER_ID = "trello"

#: Ours, not the user's. Public by Atlassian's own description, so it is read
#: from the environment for deployment rather than secrecy. Empty means the
#: one-click button is not offered and the paste form stays, which is what
#: every deployment that has not registered an app should see.
#:
#: Deliberately NOT `TRELLO_API_KEY` (2026-10-30). That name belongs to
#: mcp-trello, which pairs it with TRELLO_API_TOKEN as a single platform-wide
#: Trello account. A Trello token is bound to the key it was issued under, so
#: pointing TRELLO_API_KEY at a second app would 401 that pair and every
#: shared Trello tool with it. Measured rather than assumed: old key with old
#: token answered 200, new key with the same token answered "invalid key".
#:
#: Two keys is also the honest shape. The shared account and a person's own
#: connection are different things, and the shared one exists to be replaced
#: by connections like this rather than to be shared more widely.
ENV_KEY = "TRELLO_CONNECT_KEY"

AUTHORIZE_URL = "https://trello.com/1/authorize"

#: What the person is asked to approve, and what they will see named on
#: Trello's own page and later in their account's list of tokens.
APP_NAME = "IO"

#: read and write, because an automation that can only read cannot move a
#: card or add a comment, which is most of what anyone asks for. Trello
#: shows the person exactly this before they approve.
SCOPE = "read,write"

#: Trello offers "never" as well. A token that cannot expire is one nobody
#: can lose track of, so this is a year: long enough that it is not a
#: nuisance, short enough that an abandoned account stops being reachable.
EXPIRATION = "30days"


def api_key() -> str:
    return (os.environ.get(ENV_KEY) or "").strip()


def configured() -> bool:
    """Whether this deployment can offer the button at all.

    Without the key there is nothing to put in the authorize URL, and
    offering the button would send somebody to a Trello page that refuses
    them. The paste form still works, so this fails to the old behaviour
    rather than to nothing.
    """
    return bool(api_key())


def authorize_url(return_url: str) -> str:
    """Where to send the browser.

    `callback_method=fragment` is the default for this flow and is named
    anyway, so a reader does not have to know that to understand why the
    token arrives in the browser instead of here.
    """
    params = {
        "expiration": EXPIRATION,
        "name": APP_NAME,
        "scope": SCOPE,
        "response_type": "token",
        "key": api_key(),
        "return_url": return_url,
        "callback_method": "fragment",
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def token_from_fragment(fragment: str) -> str:
    """The token out of what the browser found after the '#'.

    Trello has sent both "#token=abc" and a bare "#abc" over the years, and
    a reader of this code should not have to find that out from a failure.
    Both are accepted; anything else is nothing.
    """
    raw = (fragment or "").lstrip("#").strip()
    if not raw:
        return ""
    if "=" in raw:
        found = urllib.parse.parse_qs(raw).get("token") or []
        return (found[0] if found else "").strip()
    return raw


#: The most Trello's own words are allowed to take up on our page. Its
#: messages are a sentence; anything longer is not a message.
MAX_REASON = 200


def error_from_fragment(fragment: str) -> str:
    """Why Trello sent somebody back without a token, in its own words.

    Documented behaviour: on a refusal Trello redirects to the return_url
    with `token=` empty and `error=<message>` in the FRAGMENT, beside the
    token rather than in the query string.

    This existed and was being discarded (2026-10-30). `token_from_fragment`
    read only the token, so every refusal became the same blank "Trello did
    not return a token", and the one place the reason was available was the
    one place nothing looked. A connect that cannot say why it failed costs
    a trawl through the logs for an answer the vendor already gave.

    Trimmed to printable characters and a sentence's worth, because this is
    vendor text on our page. The page writes it with textContent, so that is
    tidiness rather than the thing standing between us and an injection.
    """
    raw = (fragment or "").lstrip("#").strip()
    if not raw or "=" not in raw:
        return ""
    found = urllib.parse.parse_qs(raw).get("error") or []
    message = (found[0] if found else "").strip()
    return "".join(c for c in message if c.isprintable())[:MAX_REASON]


def describe_fragment(fragment: str) -> str:
    """What came back, in a form that is safe to write down.

    Names and shapes only, never a value, because the fragment is either a
    credential or somebody else's error page.

    This exists because "no usable token" was true of three different
    problems wearing the same sentence: Trello sent nothing, Trello sent a
    refusal, or Trello sent something that was not a token. Telling them
    apart took a deploy and another attempt from the person connecting, and
    the information was in hand the whole time.
    """
    raw = (fragment or "").lstrip("#").strip()
    if not raw:
        return "empty: Trello redirected back with no fragment at all"
    if "=" not in raw:
        return "one bare value, %d chars, hex=%s" % (
            len(raw), all(c in "0123456789abcdefABCDEF" for c in raw))
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    shape = []
    for name in sorted(parsed):
        value = (parsed[name] or [""])[0]
        shape.append("%s[%d chars]" % (name, len(value)))
    return "keys: " + ", ".join(shape)


#: A Trello token is hex. Checked before it is spent on a request, so an
#: error page or a fragment of HTML never reaches the vendor or the database
#: looking like a credential.
def looks_like_token(value: str) -> bool:
    v = (value or "").strip()
    return (32 <= len(v) <= 128
            and all(c in "0123456789abcdefABCDEF" for c in v))


def stored_values(user_token: str) -> dict:
    """What goes in the credential row.

    The platform key is stored beside the token rather than read from the
    environment at call time, on purpose: a connection should keep working
    exactly as it was approved, and a deployment that rotates its key should
    not silently change what every existing connection sends.
    """
    return {"api_key": api_key(), "token": user_token}
