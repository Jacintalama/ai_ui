"""Create (or reuse) the Discord #channels channel and post its pinned panel.

One-shot setup, mirroring setup_cronjob_channel.py. Idempotent: re-running
reuses a channel with the same name and posts a fresh, re-pinned panel.

Usage (inside the deployed webhook-handler container):
    docker compose -f docker-compose.unified.yml exec \
      [-e DISCORD_GUILD_ID=...] [-e CHANNELS_CHANNEL_NAME=channels] \
      webhook-handler python /app/scripts/setup_channels_channel.py

DISCORD_GUILD_ID is optional when the bot is in exactly one guild: the script
asks Discord which guilds it is in and uses the only answer. The bot needs
Manage Channels + Send Messages.
"""
import os
import sys

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.channels_panel import build_panel_payload  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0


def _only_guild(headers: dict) -> str | None:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers)
    r.raise_for_status()
    guilds = r.json()
    return guilds[0]["id"] if len(guilds) == 1 else None


def _find_channel(guild_id: str, name: str, headers: dict) -> str | None:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=headers)
    r.raise_for_status()
    for ch in r.json():
        if ch.get("type") == TEXT_CHANNEL and ch.get("name") == name:
            return ch["id"]
    return None


def _create_channel(guild_id: str, name: str, headers: dict) -> str:
    body = {"name": name, "type": TEXT_CHANNEL,
            "topic": "Talk to IO from Telegram, a terminal and more. Use the panel below."}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=headers, json=body)
    r.raise_for_status()
    return r.json()["id"]


def _post_panel(channel_id: str, payload: dict, headers: dict) -> str:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{DISCORD_API}/channels/{channel_id}/messages", headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def _pin(channel_id: str, message_id: str, headers: dict) -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.put(f"{DISCORD_API}/channels/{channel_id}/pins/{message_id}", headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: pin returned {r.status_code} {r.text}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    channel_id = os.environ.get("CHANNELS_CHANNEL_ID", "").strip()
    channel_name = os.environ.get("CHANNELS_CHANNEL_NAME", "channels").strip()
    base_url = os.environ.get("GATEWAY_PUBLIC_URL", "https://ai-ui.coolestdomain.win").strip()

    if not token:
        print("ERROR: DISCORD_BOT_TOKEN must be set.", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    try:
        if channel_id:
            print(f"Using CHANNELS_CHANNEL_ID: {channel_id}")
        else:
            if not guild_id:
                guild_id = _only_guild(headers) or ""
                if not guild_id:
                    print("ERROR: set DISCORD_GUILD_ID (the bot is in more than one guild).",
                          file=sys.stderr)
                    return 1
                print(f"Detected the bot's only guild: {guild_id}")
            found = _find_channel(guild_id, channel_name, headers)
            if found:
                channel_id = found
                print(f"Reusing existing channel #{channel_name} ({channel_id})")
            else:
                channel_id = _create_channel(guild_id, channel_name, headers)
                print(f"Created channel #{channel_name} ({channel_id})")

        message_id = _post_panel(channel_id, build_panel_payload(base_url), headers)
        _pin(channel_id, message_id, headers)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print("OK — channels panel posted and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
