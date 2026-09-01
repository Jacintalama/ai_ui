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

from routes_agents import tools_for_email

logger = logging.getLogger(__name__)

#: Providers that can show a real vendor login, because somebody registered
#: an OAuth app with that vendor. Growing this set is paperwork with the
#: vendor first and a code change second.
OAUTH_PROVIDERS = frozenset({"gmail", "gdrive", "calendar", "notion"})

#: Where a person finds the API key for the apps that take one. Without
#: this, "paste your key" is not help, it is a scavenger hunt.
PROVIDERS = {
    "gmail": {"label": "Gmail"},
    "gdrive": {"label": "Google Drive"},
    "calendar": {"label": "Google Calendar"},
    "notion": {"label": "Notion"},
    "clickup": {"label": "ClickUp",
                "where": "ClickUp, under Settings then Apps"},
    "trello": {"label": "Trello",
               "where": "trello.com/power-ups/admin, under API key"},
    "airtable": {"label": "Airtable",
                 "where": "airtable.com/create/tokens"},
    "hubspot": {"label": "HubSpot",
                "where": "HubSpot, under Settings then Integrations then Private Apps"},
    "github": {"label": "GitHub",
               "where": "github.com/settings/tokens"},
    "n8n": {"label": "n8n", "where": "your n8n instance, under Settings then API"},
    "zapier": {"label": "Zapier", "where": "zapier.com, under your account settings"},
}


def connect_hint(provider_id: str) -> dict:
    """How this app connects, and what the model should print to offer it.

    The link is a marker, not a real URL. integrations-ui.js finds it and
    turns it into a button, which is what lets one shape serve both a vendor
    login and a key paste.
    """
    meta = PROVIDERS.get(provider_id, {})
    oauth = provider_id in OAUTH_PROVIDERS
    return {
        "id": provider_id,
        "label": meta.get("label") or provider_id,
        "how": "login" if oauth else "key",
        "connect_url": "#aiui-connect:" + provider_id,
        "where": "" if oauth else (meta.get("where") or "that app's settings"),
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
        tools = data.get("tools") or []
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read what is connected", exc_info=True)
        return {"connected": [], "not_connected": []}

    connected, missing = [], []
    for t in tools:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        entry = {"id": t["id"], "label": t.get("label") or t["id"]}
        if t.get("connected"):
            connected.append(entry)
        else:
            missing.append(connect_hint(t["id"]))
    return {"connected": connected, "not_connected": missing}
