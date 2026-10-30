"""Connecting by approving, instead of by pasting a token.

Eight connectors shipped and nobody connected one in two days. The likeliest
reason is the ask itself: digging a personal access token out of a vendor's
settings page is real work, and Notion's is the most buried of the lot. OAuth
replaces it with click, approve, done.

This module is the part that can be reasoned about without a network: which
providers can do this at all, how the authorization URL is built, how a
callback's `state` is proved, and how the token response is read. The route
layer owns the redirect and the exchange.

Two things here are security rather than plumbing.

`state` is bound to the user who started the flow and spendable exactly once.
Without the binding, anyone who can get a signed-in browser to follow a
callback URL can attach THEIR vendor account to YOUR user. That is account
grafting, not a login bug, and it is silent.

And this degrades. Until a deployment registers a developer app with the vendor
and sets a client id and secret, `configured()` is False and the dialog keeps
offering the paste-a-token form it has today. A Connect button that strands
someone on a vendor's error page is worse than a form that works.
"""
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

#: How long a half-finished authorization stays valid. Notion's own codes are
#: short lived; this only has to outlast a human reading a consent screen.
STATE_TTL_SEC = 900


def _env(name: str, default: str = "") -> str:
    """Indirection so tests can drive configured() without touching os.environ."""
    return os.environ.get(name, default)


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    label: str
    authorize_endpoint: str
    token_endpoint: str
    #: Extra query parameters the vendor requires on the authorize URL.
    authorize_extra: Dict[str, str]
    #: (token json) -> (credential values, account label). Raises ValueError if
    #: the vendor did not actually return a token.
    read_token: Callable[[dict], Tuple[Dict[str, str], str]]
    #: Vendors differ: Notion wants HTTP Basic, most want the id and secret in
    #: the form body.
    token_auth: str = "basic"


def _notion_token(payload: dict) -> Tuple[Dict[str, str], str]:
    token = (payload or {}).get("access_token") or ""
    if not token:
        # Some flows return 200 with an error body. Storing an empty credential
        # would produce a card claiming a connection that cannot work.
        raise ValueError("Notion did not return an access token.")
    label = ((payload or {}).get("workspace_name")
             or ((payload or {}).get("owner") or {}).get("name")
             or "Notion workspace")
    # Bounded and de-tagged where it enters, as well as escaped where it is
    # rendered. This is a name a third party chose and we put on a page.
    clean = "".join(c for c in str(label) if c not in "<>").strip()
    return {"token": token}, (clean or "Notion workspace")[:80]


PROVIDERS: Dict[str, OAuthProvider] = {
    "notion": OAuthProvider(
        id="notion",
        label="Notion",
        authorize_endpoint="https://api.notion.com/v1/oauth/authorize",
        token_endpoint="https://api.notion.com/v1/oauth/token",
        # owner=user is what makes this a per-person grant rather than an
        # internal integration bound to one workspace.
        authorize_extra={"response_type": "code", "owner": "user"},
        read_token=_notion_token,
        token_auth="basic",
    ),
}


#: Vendors whose one-click connect is NOT an OAuth 2.0 code exchange, so they
#: cannot live in PROVIDERS above and are handled by their own route.
#:
#: Trello (2026-10-30) is the only one. It offers exactly two ways to get a
#: user token, and neither is OAuth 2.0: its own `1/authorize` flow, and
#: OAuth 1.0a. Atlassian's RFC-89 proposed adding OAuth 2.0 and then
#: deprecating both, but nothing confirms it has shipped, so this is the
#: ground truth to build on rather than something to wait out.
#:
#: `1/authorize` is the one used here, and Trello's own guide calls it the
#: simpler route. The token comes back in the URL FRAGMENT, which a server
#: never receives, so trello_connect.py serves a page that reads it in the
#: browser and posts it back.
NON_OAUTH2_ONE_CLICK = frozenset({"trello"})


def one_click(provider_id: str) -> bool:
    """Whether this vendor can be connected without pasting a credential, by
    any route. What the card should offer a button for."""
    pid = provider_id or ""
    return pid in PROVIDERS or pid in NON_OAUTH2_ONE_CLICK


def supports_oauth(provider_id: str) -> bool:
    """Whether this vendor can do OAuth 2.0, the code exchange this module
    implements.

    False for n8n, which is the user's own server, and for Zapier, whose Catch
    Hook is a webhook rather than a grant. Neither will ever offer this, and a
    card must not imply otherwise. Also false for Trello, which has a
    one-click connect but not this one: see NON_OAUTH2_ONE_CLICK.
    """
    return (provider_id or "") in PROVIDERS


def _env_names(provider_id: str) -> Tuple[str, str]:
    stem = provider_id.upper().replace("-", "_")
    return stem + "_CLIENT_ID", stem + "_CLIENT_SECRET"


def configured(provider_id: str) -> bool:
    """Whether this deployment can actually complete the flow.

    Half configured counts as off. An id with no secret cannot complete an
    exchange, so offering the button would strand the user on the vendor's site
    with nothing to come back to.
    """
    if not supports_oauth(provider_id):
        return False
    cid, csec = _env_names(provider_id)
    return bool(_env(cid) and _env(csec))


def client_credentials(provider_id: str) -> Tuple[str, str]:
    cid, csec = _env_names(provider_id)
    return _env(cid), _env(csec)


def authorize_url(provider_id: str, client_id: str, redirect_uri: str,
                  state: str) -> str:
    """Where to send the browser to ask for consent."""
    provider = PROVIDERS.get(provider_id or "")
    if not provider:
        raise ValueError("No OAuth for provider: " + str(provider_id))
    params = {"client_id": client_id, "redirect_uri": redirect_uri,
              "state": state}
    params.update(provider.authorize_extra)
    return provider.authorize_endpoint + "?" + urlencode(params)


def read_token_response(provider_id: str, payload: dict):
    provider = PROVIDERS.get(provider_id or "")
    if not provider:
        raise ValueError("No OAuth for provider: " + str(provider_id))
    return provider.read_token(payload or {})


class StateStore:
    """CSRF states, in process memory, spendable once.

    In memory on purpose: a state outliving a restart buys nothing, and the
    worst case is a user clicking Connect again. Expired entries are swept on
    every mint, because an abandoned flow must not leak an entry forever.
    """

    def __init__(self):
        self._states: Dict[str, Tuple[str, float]] = {}

    def mint(self, email: str, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        for key in [k for k, (_, exp) in self._states.items() if exp < now]:
            self._states.pop(key, None)
        state = secrets.token_urlsafe(24)
        self._states[state] = (email, now + STATE_TTL_SEC)
        return state

    def consume(self, state: Optional[str],
                now: Optional[float] = None) -> Optional[str]:
        """The email that started this flow, or None. Removes it either way."""
        now = time.time() if now is None else now
        item = self._states.pop((state or "").strip(), None)
        if not item:
            return None
        email, expires = item
        return email if expires >= now else None

    def size(self) -> int:
        return len(self._states)

    def clear(self) -> None:
        self._states.clear()


#: One store for the service. Module level so the start and the callback, which
#: are separate requests, see the same states.
STATES = StateStore()
