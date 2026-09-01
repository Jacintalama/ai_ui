"""What somebody has connected, and how they would connect the rest.

Read only. This is the half that lets the assistant say "you have no
ClickUp" rather than guessing, and it is what every offer it makes depends
on. Nothing here changes anything, which is why it needs no confirmation
step and can be handed to every model.

The universe of connectable apps is eleven: the three Google services
(Gmail, Calendar, Drive) plus the eight Connect Your Own App providers in
connections.PROVIDERS. This used to read routes_agents.tools_for_email,
which lists INSTALLED OPEN WEBUI TOOLS, not connectable apps: on a real
account that list is calendar, documents, excel_creator,
executive_dashboard, gdrive, gmail, remember and server:mcp-proxy, so the
only thing it could ever offer to connect was the raw internal id
"server:mcp-proxy". Connection state now comes from
routes_agents._connected_providers, which already covers both the three
Google token tables and tasks.user_connections in one query, and fails
toward "nothing connected" on a read error.

The split that matters is `how`. Only a provider with a real, currently
configured OAuth app can show a vendor login; everything else takes a
pasted API key. See _can_log_in: it is derived, not a fixed list, because a
fixed list goes stale in the dangerous direction, promising a login that
503s the moment a vendor is added to oauth_providers.py before its client
id and secret are actually configured on this box.
"""
import logging

from connections import PROVIDERS as CANONICAL_PROVIDERS
from routes_agents import _connected_providers

logger = logging.getLogger(__name__)

#: The three Google services, each with its own login already wired
#: (auth/google/start) and no dependency on oauth_providers.py. Labels live
#: here because connections.PROVIDERS only carries the eight Connect Your
#: Own App providers; the Google ones are not in it.
GOOGLE_LABELS = {
    "gmail": "Gmail",
    "calendar": "Google Calendar",
    "gdrive": "Google Drive",
}
GOOGLE_SERVICES = frozenset(GOOGLE_LABELS)

#: Every connectable app: the three Google services, then the eight in
#: connections.PROVIDERS, in that module's own order. Eleven total.
ALL_PROVIDER_IDS = tuple(GOOGLE_LABELS) + tuple(CANONICAL_PROVIDERS)


def _can_log_in(provider_id: str) -> bool:
    """Whether this app can really show a vendor login right now.

    Derived rather than hardcoded, because a hardcoded list goes stale in
    the dangerous direction: it promises a login that 503s. Notion supports
    OAuth but has no client id configured on this box, so today it is a key
    paste, and it becomes a login the moment somebody configures it, with no
    code change.
    """
    if provider_id in GOOGLE_SERVICES:
        return True
    try:
        import oauth_providers as O
        return bool(O.supports_oauth(provider_id) and O.configured(provider_id))
    except Exception:                                       # noqa: BLE001
        return False


def _label_for(provider_id: str) -> str:
    """A human label for `provider_id`: Google's own name, then the
    canonical connections.py label, then the bare id as a last resort that
    should never actually happen for anything in ALL_PROVIDER_IDS."""
    if provider_id in GOOGLE_LABELS:
        return GOOGLE_LABELS[provider_id]
    provider = CANONICAL_PROVIDERS.get(provider_id)
    return provider.label if provider else provider_id


def connect_hint(provider_id: str) -> dict:
    """How this app connects, and what the model should print to offer it.

    The link is a marker, not a real URL. integrations-ui.js finds it and
    turns it into a button, which is what lets one shape serve both a vendor
    login and a key paste.

    Returns a dict with an empty label and where if provider_id is not a
    string, so the caller can detect invalid input.
    """
    if not isinstance(provider_id, str):
        return {
            "id": provider_id,
            "label": "",
            "how": "key",
            "connect_url": "",
            "where": "",
        }
    can_log_in = _can_log_in(provider_id)
    label = _label_for(provider_id)
    canonical = CANONICAL_PROVIDERS.get(provider_id)
    where = "" if can_log_in else (canonical.where if canonical else "that app's settings")
    return {
        "id": provider_id,
        "label": label,
        "how": "login" if can_log_in else "key",
        "connect_url": "#aiui-connect:" + provider_id,
        "where": where,
    }


async def summarise(email: str) -> dict:
    """What this person has connected, and how to connect what they have not.

    Never raises. A broken read degrades to the emptiest honest answer,
    because an assistant that cannot check is still useful and one that
    crashes is not.
    """
    if not email:
        return {"connected": [], "not_connected": []}
    try:
        connected_ids = await _connected_providers(email)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read what is connected", exc_info=True)
        return {"connected": [], "not_connected": []}

    connected, missing = [], []
    for pid in ALL_PROVIDER_IDS:
        if pid in connected_ids:
            connected.append({"id": pid, "label": _label_for(pid)})
        else:
            missing.append(connect_hint(pid))
    return {"connected": connected, "not_connected": missing}
