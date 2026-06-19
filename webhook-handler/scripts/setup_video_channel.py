"""Create (or reuse) the Discord #video-generation channel and post its panel.

One-shot, idempotent. Usage:
    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
    [VIDEO_CHANNEL_ID=<snowflake>] [VIDEO_CHANNEL_NAME=video-generation] \
    python webhook-handler/scripts/setup_video_channel.py
The bot must be in the guild with Manage Channels + Send Messages.
"""
import os
import sys

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.video_panel import build_video_embed, build_video_panel  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0


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
            "topic": "Generate narrated videos from screenshots with AIUI — use the panel below."}
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
    channel_id = os.environ.get("VIDEO_CHANNEL_ID", "").strip()
    channel_name = os.environ.get("VIDEO_CHANNEL_NAME", "video-generation").strip()
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN must be set.", file=sys.stderr)
        return 1
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = {**build_video_panel(), "embeds": [build_video_embed()]}
    try:
        if channel_id:
            print(f"Using channel ID from VIDEO_CHANNEL_ID: {channel_id}")
        else:
            if not guild_id:
                print("ERROR: DISCORD_GUILD_ID must be set when VIDEO_CHANNEL_ID is empty.",
                      file=sys.stderr)
                return 1
            found = _find_channel(guild_id, channel_name, headers)
            channel_id = found or _create_channel(guild_id, channel_name, headers)
            print(("Reusing" if found else "Created") + f" channel #{channel_name} ({channel_id})")
        message_id = _post_panel(channel_id, payload, headers)
        _pin(channel_id, message_id, headers)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    print("OK — video panel posted and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
