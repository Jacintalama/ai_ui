"""Create (or reuse) the Discord App Builder channel and post its button panel.

One-shot setup, modeled on scripts/register_discord_commands.py. Idempotent:
re-running reuses a channel with the same name and posts a fresh, re-pinned panel.

Usage (in the repo):
    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
    [TASKS_URL=http://tasks:8210] [APP_BUILDER_SETUP_EMAIL=admin@example.com] \
    [APP_BUILDER_CHANNEL_NAME=app-builder] \
    python webhook-handler/scripts/setup_app_builder_channel.py

Usage (inside the deployed webhook-handler container, on the backend network so
TASKS_URL=http://tasks:8210 resolves):
    docker compose -f docker-compose.unified.yml exec \
      -e DISCORD_GUILD_ID=... -e APP_BUILDER_SETUP_EMAIL=admin@example.com \
      webhook-handler python /app/scripts/setup_app_builder_channel.py

The bot must be in the guild with Manage Channels + Send Messages.
"""
import os
import sys

import httpx

# Import the pure panel builder from the webhook-handler package. This script
# lives in webhook-handler/scripts/, so the parent dir holds the `handlers`
# package — both in the repo and inside the container image (where this file is
# /app/scripts/... and `handlers` is /app/handlers).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.app_builder_panel import build_panel_payload  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0  # Discord guild text-channel type


def _fetch_templates(tasks_url: str, email: str) -> list[dict]:
    url = f"{tasks_url.rstrip('/')}/api/aiuibuilder/templates"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers={"X-User-Email": email})
        r.raise_for_status()
    return r.json()


def _find_channel(guild_id: str, name: str, headers: dict) -> str | None:
    url = f"{DISCORD_API}/guilds/{guild_id}/channels"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    for ch in r.json():
        if ch.get("type") == TEXT_CHANNEL and ch.get("name") == name:
            return ch["id"]
    return None


def _create_channel(guild_id: str, name: str, headers: dict) -> str:
    url = f"{DISCORD_API}/guilds/{guild_id}/channels"
    body = {"name": name, "type": TEXT_CHANNEL,
            "topic": "Build apps with AIUI — pick a template below."}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=body)
    r.raise_for_status()
    return r.json()["id"]


def _post_panel(channel_id: str, payload: dict, headers: dict) -> str:
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def _pin(channel_id: str, message_id: str, headers: dict) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/pins/{message_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.put(url, headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: pin returned {r.status_code} {r.text}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    tasks_url = os.environ.get("TASKS_URL", "http://tasks:8210").strip()
    email = os.environ.get("APP_BUILDER_SETUP_EMAIL", "").strip()
    if not email:
        admins = os.environ.get("ADMIN_EMAILS", "").strip()
        email = admins.split(",")[0].strip() if admins else ""
    channel_name = os.environ.get("APP_BUILDER_CHANNEL_NAME", "app-builder").strip()

    if not token or not guild_id:
        print("ERROR: DISCORD_BOT_TOKEN and DISCORD_GUILD_ID must be set.", file=sys.stderr)
        return 1
    if not email:
        print("ERROR: set APP_BUILDER_SETUP_EMAIL (or ADMIN_EMAILS) to fetch the catalog.",
              file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    try:
        templates = _fetch_templates(tasks_url, email)
    except Exception as e:
        print(f"ERROR: could not fetch templates from {tasks_url}: {e}", file=sys.stderr)
        return 2
    if not templates:
        print("ERROR: template catalog is empty.", file=sys.stderr)
        return 2

    payload = build_panel_payload(templates)

    try:
        channel_id = _find_channel(guild_id, channel_name, headers)
        if channel_id:
            print(f"Reusing existing channel #{channel_name} ({channel_id})")
        else:
            channel_id = _create_channel(guild_id, channel_name, headers)
            print(f"Created channel #{channel_name} ({channel_id})")
        message_id = _post_panel(channel_id, payload, headers)
        _pin(channel_id, message_id, headers)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK — panel posted ({len(templates)} templates) and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
