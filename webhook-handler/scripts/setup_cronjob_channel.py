"""Create (or reuse) the Discord cron-job channel and post its button panel.

One-shot setup. Idempotent: re-running reuses a channel with the same name
and posts a fresh, re-pinned panel.

Usage (in the repo):
    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
    [CRONJOB_CHANNEL_ID=1508420480283967509] \
    [CRONJOB_CHANNEL_NAME=cron-jobs] \
    python webhook-handler/scripts/setup_cronjob_channel.py

Usage (inside the deployed webhook-handler container):
    docker compose -f docker-compose.unified.yml exec \
      -e DISCORD_GUILD_ID=... \
      webhook-handler python /app/scripts/setup_cronjob_channel.py

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
from handlers.cronjob_panel import build_panel_payload  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0  # Discord guild text-channel type


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
            "topic": "Schedule prompts with AIUI — use the panel below."}
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
    channel_id = os.environ.get("CRONJOB_CHANNEL_ID", "1508420480283967509").strip()
    channel_name = os.environ.get("CRONJOB_CHANNEL_NAME", "cron-jobs").strip()

    if not token:
        print("ERROR: DISCORD_BOT_TOKEN must be set.", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    payload = build_panel_payload()

    try:
        # Priority 1: use explicit channel ID if provided and non-empty
        if channel_id:
            print(f"Using channel ID from CRONJOB_CHANNEL_ID: {channel_id}")
        else:
            # Fall back to find-or-create by name (requires guild_id)
            if not guild_id:
                print("ERROR: DISCORD_GUILD_ID must be set when CRONJOB_CHANNEL_ID is empty.",
                      file=sys.stderr)
                return 1
            found = _find_channel(guild_id, channel_name, headers)
            if found:
                channel_id = found
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

    print("OK — cron-job panel posted and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
