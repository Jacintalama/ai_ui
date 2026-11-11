"""Renewing a connected account's token before it dies.

The gap this closes was documented in `oauth_providers` long before it was
filled, and the comment is worth repeating because it says why this is the
prerequisite for the last two one-click apps rather than a nicety:

    HubSpot and Airtable both return a `refresh_token` and an access token
    that dies in under an hour: HubSpot in 1800 seconds, Airtable in 3600.
    Nothing in this service refreshes anything. So a one-click HubSpot
    connect would work for half an hour and then quietly stop, and the card
    would still say "Connected" because a stored credential is all it checks.
    The paste form it would replace hands over a private-app token that never
    expires, so the button would be a downgrade.

    Both become small once a refresh exists. That is the order: refresh
    first, then these two, and `read_token` returning expires_in is where it
    starts.

Everything here is a decision with no I/O in it, so all of it can be tested
without a network, a clock or a database. The route layer owns the request and
the encrypted store, exactly as it does for connecting.

WHERE THE EXPIRY LIVES. A credential is Fernet-encrypted JSON in
`tasks.user_connections.secrets_encrypted`, not a set of columns, so the
expiry and the refresh token go in that blob beside the access token. No
migration, and nothing else has to know: `connections.vendor_auth` reads the
field names it wants and ignores the rest, which is already how ClickUp's
`scheme` rides along.

THE MARGINS ARE COPIED, NOT INVENTED. `_ensure_fresh_token` in
`routes_supabase_oauth.py` is the working precedent in this repository: it
renews at expiry minus 30 seconds and records the new expiry 60 seconds short
of what the vendor said. Two numbers, both earned, both kept.

AND ABSENT MEANS LEAVE IT ALONE. ClickUp, GitHub and Trello all hand over
credentials with no expiry at all, which is precisely why nobody noticed this
missing. A credential with no `expires_at` is never renewed and never asks a
vendor for anything, so every connection that exists today behaves exactly as
it did before this module existed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

#: Renew this long before the token actually dies. Waiting for the exact
#: second guarantees a race with the request already in flight.
SKEW_SEC = 30

#: Record the expiry this much short of what the vendor said, so a token is
#: never used in the last minute of its life.
MARGIN_SEC = 60


def _clock(now: Optional[float] = None) -> float:
    return time.time() if now is None else float(now)


def expiry_from(payload: dict, now: Optional[float] = None) -> float:
    """When a token response's token should stop being used, as epoch seconds.

    0.0 means the vendor named no expiry, which is not the same as "expires
    now": it is every credential this platform holds today.
    """
    raw = (payload or {}).get("expires_in")
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return 0.0
    if seconds <= 0:
        return 0.0
    return _clock(now) + seconds - MARGIN_SEC


def with_expiry(values: Dict[str, str], payload: dict,
                now: Optional[float] = None) -> Dict[str, str]:
    """A credential plus whatever a token response said about renewing it.

    Called on the way IN, by `oauth_providers.read_token`, because a refresh
    token the exchange threw away cannot be recovered later: the vendor sends
    it once. Inert for a vendor that sends neither, which is all three
    providers connected today.
    """
    out = dict(values or {})
    refresh = (payload or {}).get("refresh_token")
    if refresh:
        out["refresh_token"] = refresh
    at = expiry_from(payload, now)
    if at:
        out["expires_at"] = at
    return out


def expired(values: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Whether this credential should be renewed before it is used.

    False when there is no expiry, which is the common case and must stay
    cheap. True when the stored expiry cannot be read at all: a garbled
    expiry is not evidence that a token is good, and renewing on it costs one
    request where trusting it strands the credential for good.
    """
    raw = (values or {}).get("expires_at")
    if raw in (None, ""):
        return False
    try:
        at = float(raw)
    except (TypeError, ValueError):
        return True
    return at <= _clock(now) + SKEW_SEC


def refreshable(provider_id: str, values: Dict[str, str]) -> bool:
    """Whether there is anything to ask, and anyone to ask.

    False without a refresh token, which covers every credential stored
    before this existed and every token anybody pastes into the form. False
    for a vendor with no OAuth: n8n is the person's own server and Zapier's
    Catch Hook is a webhook rather than a grant, so neither has a token
    endpoint.
    """
    if not (values or {}).get("refresh_token"):
        return False
    # Local import: `oauth_providers` imports this module for `with_expiry`,
    # and a module-level import here would make that a cycle.
    import oauth_providers as O
    return O.supports_oauth(provider_id)


def refresh_post(provider_id: str, values: Dict[str, str]) -> Dict[str, Any]:
    """The exact request that renews this credential.

    Encoded the way that vendor wants it, read off the provider rather than
    guessed: Notion documents HTTP Basic and a JSON body, GitHub documents
    neither and gets the form encoding RFC 6749 specifies. Getting this wrong
    on a renewal is the same 400 as getting it wrong on the exchange, and the
    exchange already learned it.
    """
    import oauth_providers as O

    provider = O.PROVIDERS.get(provider_id or "")
    if not provider:
        raise ValueError("No OAuth for provider: " + str(provider_id))
    refresh = (values or {}).get("refresh_token") or ""
    if not refresh:
        raise ValueError("No refresh token stored for " + provider.label + ".")

    client_id, client_secret = O.client_credentials(provider_id)
    body: Dict[str, str] = {"grant_type": "refresh_token",
                            "refresh_token": refresh}
    post: Dict[str, Any] = {
        "url": provider.token_endpoint,
        # GitHub answers in `key=value&key=value` unless asked for JSON, and
        # the others are unbothered by being asked.
        "headers": {"Accept": "application/json"},
    }
    if provider.token_auth == "basic":
        # httpx builds the standard base64 header, which is what Notion
        # wants and has always had.
        post["auth"] = (client_id, client_secret)
    else:
        # {} unless the vendor wants base64URL, which only Airtable does.
        post["headers"].update(O.basic_header(provider_id))
        if O.client_in_body(provider_id):
            body["client_id"] = client_id
            body["client_secret"] = client_secret
    post["json" if provider.token_body == "json" else "data"] = body
    return post


def after_refresh(values: Dict[str, str], payload: dict,
                  now: Optional[float] = None) -> Dict[str, str]:
    """The credential to store once the vendor has answered.

    Three things this gets right that rebuilding it from the payload would
    not:

    The old refresh token survives a vendor that does not rotate one. Some
    send a new one on every renewal and some never send one again, so
    Supabase's `tok.get("refresh_token") or refresh` is copied here. Without
    it the second renewal has nothing to send.

    Everything unrelated survives. ClickUp keeps `scheme: Bearer` beside its
    token because an OAuth token sent raw is a 401, so a renewal that kept
    only the token would produce a credential that fails with a message about
    a bad credential when the credential is fine.

    And a response with no token in it is refused rather than stored. Vendors
    answer 200 with an error body, and storing that replaces a working
    credential with an empty one.
    """
    payload = payload or {}
    token = payload.get("access_token") or ""
    if not token:
        raise ValueError("The vendor did not return a new access token.")

    out = dict(values or {})
    out["token"] = token
    rotated = payload.get("refresh_token")
    if rotated:
        out["refresh_token"] = rotated
    at = expiry_from(payload, now)
    if at:
        out["expires_at"] = at
    else:
        # The vendor renewed the token and named no lifetime for it. Keeping
        # the old expiry, which is already in the past, would renew on every
        # single call. Dropping it means we stop renewing and fall back to
        # the 401 path, which says "reconnect" in plain words. Hypothetical
        # for the vendors this serves, since one that issues refresh tokens
        # states an expiry, but it has to land somewhere.
        out.pop("expires_at", None)
    return out
