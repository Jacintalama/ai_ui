"""Who may see a tool, and who may run one.

Split out of main.py because the same three-line decision was written three
times and got written wrong all three times, in the same way: the access check
was guarded by `if user_email:`, so a caller the proxy could NOT identify
skipped the check rather than failing it. `/meta/*` is public, so that meant an
unauthenticated request from the internet could search every tool, read its
schema, and execute it against the platform's own shared credentials.

Two rules, and they are the whole module:

1. An unidentified caller is refused. Not served, not filtered, refused.
2. An allow-list is always a set, and an EMPTY set denies everything.

Rule 2 is not pedantry. The original expression was
`if allowed_servers and tool["tenant_id"] not in allowed_servers: deny`, and an
empty list is falsy, so "this user was granted nothing" and "do not filter"
were the same value. Returning a set with no members, and testing membership
rather than truthiness, is what keeps those two apart.
"""
from typing import Iterable, Optional, Set

from fastapi import HTTPException

#: Said to a caller the proxy cannot identify. Deliberately about signing in
#: rather than about tenants: someone hitting this either forgot their session
#: or was never entitled to one, and neither needs the server list described.
UNIDENTIFIED_DETAIL = "Sign in to use tools."


def require_identified(user_email: Optional[str]) -> str:
    """The caller's email, or refuse the request.

    Called at the TOP of every meta endpoint, before any lookup, so that no
    code path can reach a tool without having answered "who is asking".
    """
    if not user_email or not str(user_email).strip():
        raise HTTPException(status_code=401, detail=UNIDENTIFIED_DETAIL)
    return user_email


def servers_for_caller(user_email: Optional[str],
                       tenant_ids: Optional[Iterable[str]]) -> Set[str]:
    """The servers this caller may use. Empty means none, never means all."""
    require_identified(user_email)
    return set(tenant_ids or ())


def may_use_server(allowed_servers: Set[str], server_id: str) -> bool:
    """Membership, not truthiness. See rule 2 above."""
    return server_id in (allowed_servers or set())
