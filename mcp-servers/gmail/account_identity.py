"""One account, one key: the email address.

Every per-user table on this platform is keyed by the account's email, and
every lookup asks by email. The browser, though, does not always know it.
Open WebUI's JWT carries a user `id` and no address, so `integrations-ui.js`
answered "who is signed in?" with that id whenever it was asked before the
real address had been fetched (it was fetched a second after load, and only
then). A `connect=all` consent started inside that window wrote the id, not
the address, into `gmail_tokens`, `gdrive_tokens` and `calendar_tokens`
alike.

One account was connected and unreachable at the same time, in all three
services, and nothing reported an error: the write succeeded, and every later
read asked for the address and correctly found nothing.

The browser no longer answers with an id. This module is the other half of the
fix, because the browser is not the only client: the Discord and Slack flows
sign an identity into the OAuth state, and a signed id would land here just
the same. Whatever arrives, the address is what gets stored, so no client can
key a token row by anything else again.
"""
import re
from typing import Awaitable, Callable, Optional

#: Deliberately loose. This does not validate an address, it only has to tell
#: one apart from an Open WebUI user id (a UUID). A false rejection here would
#: lock somebody out of their own connection, so the bar is "has an @".
_HAS_AT = re.compile(r"^[^@\s]+@[^@\s]+$")

#: What an Open WebUI user id looks like, used only to say so in a message.
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


#: Addresses that are placeholders rather than accounts. `default@local` is
#: this service's dev fallback, and the browser falls back to it too when it
#: cannot say who is signed in. It has an @, so it passes every shape test,
#: which makes it the one remaining way a token could be stored under a key
#: two different people share. In production it is not an identity.
PLACEHOLDERS = frozenset({"default@local", "unknown@local", "anonymous@local"})


class UnknownAccount(Exception):
    """An identity arrived that is not an address and resolves to no account.

    Raised on the write path only. Storing a token under a key nothing will
    ever ask for is the exact failure this module exists to prevent, so the
    connect fails loudly instead of appearing to succeed.
    """


def looks_like_email(identity: str) -> bool:
    """True when `identity` is an address rather than an id."""
    return bool(_HAS_AT.match((identity or "").strip()))


def looks_like_user_id(identity: str) -> bool:
    """True when `identity` has the shape of an Open WebUI user id."""
    return bool(_UUID.match((identity or "").strip()))


async def canonical_email(
    identity: str,
    fetch_email: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
    *,
    required: bool = False,
    placeholders_ok: bool = False,
) -> str:
    """The address for `identity`, which is usually already one.

    An address is returned untouched and costs no database round trip, which
    is the case on every request once the clients are correct. Anything else
    is looked up through `fetch_email`, an id -> address callable, so this
    stays testable without a database.

    `required` is the difference between the two paths. Reading is forgiving:
    an identity that resolves to nothing comes back unchanged and the caller
    reports "not connected", which is what it would have done anyway. Writing
    is not: it raises `UnknownAccount`, because a token stored under an
    unaskable key is worse than a connect that visibly failed.

    `placeholders_ok` is for a box with no database, where `default@local` is
    the only account there is. Anywhere else a placeholder is refused on the
    write path, because it is a key more than one person would answer to.
    """
    key = (identity or "").strip()
    if key in PLACEHOLDERS and required and not placeholders_ok:
        raise UnknownAccount(
            "Cannot connect an account as %r: that is a placeholder, not an "
            "address, and a token stored under it would not belong to anyone "
            "in particular. Reload the page and try again." % key
        )
    if looks_like_email(key):
        return key
    resolved = None
    if key and fetch_email is not None:
        resolved = await fetch_email(key)
        if resolved:
            resolved = resolved.strip()
    if resolved and looks_like_email(resolved):
        return resolved
    if required:
        what = "user id" if looks_like_user_id(key) else "identity"
        raise UnknownAccount(
            "Cannot connect an account from a %s (%r): the address is what "
            "every per-user table is keyed by. Reload the page and try "
            "again." % (what, key)
        )
    return key
