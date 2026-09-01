"""What somebody has connected, and how they would connect the rest.

Read only. This is the half that lets the assistant say "you have no
ClickUp" rather than guessing, and it is what every offer it makes depends
on. Nothing here changes anything, which is why it needs no confirmation
step and can be handed to every model.

The split that matters is `how`. Only Google and Notion have a registered
OAuth app, so only they can show a real vendor login. The other seven take
a pasted API key. Telling somebody to "log in to ClickUp" when no such flow
exists would send them looking for a button that is not there.
"""
import logging

from connections import PROVIDERS as CANONICAL_PROVIDERS
from routes_agents import tools_for_email

logger = logging.getLogger(__name__)

#: Providers that can show a real vendor login, because somebody registered
#: an OAuth app with that vendor. Growing this set is paperwork with the
#: vendor first and a code change second.
OAUTH_PROVIDERS = frozenset({"gmail", "gdrive", "calendar", "notion"})

#: Metadata for all providers. Labels come from the canonical source;
#: we keep this only for the OAuth membership.
PROVIDERS = {pid: p for pid, p in CANONICAL_PROVIDERS.items()}


def connect_hint(provider_id: str) -> dict:
    """How this app connects, and what the model should print to offer it.

    The link is a marker, not a real URL. integrations-ui.js finds it and
    turns it into a button, which is what lets one shape serve both a vendor
    login and a key paste.

    Returns a dict with an empty label and where if provider_id is not a
    string or is not found, so the caller can detect invalid input.
    """
    if not isinstance(provider_id, str):
        return {
            "id": provider_id,
            "label": "",
            "how": "key",
            "connect_url": "",
            "where": "",
        }
    provider = PROVIDERS.get(provider_id)
    oauth = provider_id in OAUTH_PROVIDERS
    label = provider.label if provider else provider_id
    where = "" if oauth else (provider.where if provider else "that app's settings")
    return {
        "id": provider_id,
        "label": label,
        "how": "login" if oauth else "key",
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
        data = await tools_for_email(email)
        tools = data.get("tools")
        if not isinstance(tools, (list, tuple)):
            logger.warning("tools is not a list or tuple", extra={"type": type(tools)})
            return {"connected": [], "not_connected": []}
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read what is connected", exc_info=True)
        return {"connected": [], "not_connected": []}

    connected, missing = [], []
    for t in tools:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str):
            continue
        entry = {"id": t["id"], "label": t.get("label") or t["id"]}
        if t.get("connected"):
            connected.append(entry)
        else:
            missing.append(connect_hint(t["id"]))
    return {"connected": connected, "not_connected": missing}
