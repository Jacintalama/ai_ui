"""Connecting Trello in one click (2026-10-30).

Before this, a person had to open trello.com/power-ups/admin, create a
Power-Up to get an API key, copy it, click a Token link beside it, and copy
that too. Four steps and two pastes, and the step where somebody who is not
a developer gives up. Automations are worth nothing if nobody gets as far as
connecting the app they want automated.

**Trello has no OAuth 2.0.** Checked against Atlassian's own docs rather than
assumed: it offers its `1/authorize` flow and OAuth 1.0a, and nothing else.
RFC-89 proposed adding OAuth 2.0 and then deprecating both, but nothing
confirms it shipped, so this builds on what exists today. That is why Trello
cannot use oauth_providers.py, which is a code exchange and only that.

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
#: every deployment that has not registered a Power-Up should see.
ENV_KEY = "TRELLO_API_KEY"

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
