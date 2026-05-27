"""Post the Scheduled-tasks (cron job) panel to the dedicated cron-job channel.

The scheduled-tasks entry point used to live as a second pinned panel in the
#app-builder channel. This script relocates it: it posts + pins the schedules
panel to the cron-job channel and removes any stale schedules panel still
pinned in #app-builder. Idempotent — re-running clears the old panel(s) first.

Usage (inside the deployed webhook-handler container):
    docker compose -f docker-compose.unified.yml exec \
      -e CRONJOB_CHANNEL_ID=1508420480283967509 \
      webhook-handler python /app/scripts/setup_cronjob_channel.py

DISCORD_BOT_TOKEN is read from the container environment. The guild is derived
from the cron channel, so DISCORD_GUILD_ID is not required. The bot must have
Manage Messages in both channels (to pin / unpin).

Env:
    CRONJOB_CHANNEL_ID        target channel (default 1508420480283967509)
    APP_BUILDER_CHANNEL_NAME  channel to clean stale panels from (default app-builder)
    CRONJOB_SKIP_CLEANUP=1    skip removing the panel from #app-builder
"""
import os
import sys

import httpx

# This script lives in webhook-handler/scripts/, so the parent dir holds the
# `handlers` package — both in the repo and inside the container image (where
# this file is /app/scripts/... and `handlers` is /app/handlers).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.app_builder_panel import build_schedules_panel  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0  # Discord guild text-channel type
DEFAULT_CRON_CHANNEL_ID = "1508420480283967509"

# Schedules-panel messages are identified by the word "schedul" in their text
# or embed (title/description) — matches both the old plain-text panel and the
# new embed panel, and never the app-builder panel ("app builder").
def _is_schedule_panel(msg: dict) -> bool:
    if not (msg.get("author") or {}).get("bot"):
        return False
    blob = msg.get("content") or ""
    for e in msg.get("embeds") or []:
        blob += " " + (e.get("title") or "") + " " + (e.get("description") or "")
    return "schedul" in blob.lower()


def _get_channel(channel_id: str, headers: dict) -> dict:
    url = f"{DISCORD_API}/channels/{channel_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
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


def _list_messages(channel_id: str, headers: dict, limit: int = 100) -> list[dict]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages?limit={limit}"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def _unpin(channel_id: str, message_id: str, headers: dict) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/pins/{message_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.delete(url, headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: unpin returned {r.status_code} {r.text}", file=sys.stderr)


def _delete_message(channel_id: str, message_id: str, headers: dict) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.delete(url, headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: delete message returned {r.status_code} {r.text}", file=sys.stderr)


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


def _remove_schedule_panels(channel_id: str, headers: dict) -> int:
    """Delete the bot's schedules-panel messages in a channel (unpinning first
    if pinned). Scans recent history rather than only pins, since the bot may
    lack Manage Messages (pinning) in a channel. Returns count removed."""
    removed = 0
    for msg in _list_messages(channel_id, headers):
        if _is_schedule_panel(msg):
            mid = msg["id"]
            if msg.get("pinned"):
                _unpin(channel_id, mid, headers)
            _delete_message(channel_id, mid, headers)
            removed += 1
    return removed


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    cron_channel_id = os.environ.get(
        "CRONJOB_CHANNEL_ID", DEFAULT_CRON_CHANNEL_ID).strip()
    app_builder_name = os.environ.get(
        "APP_BUILDER_CHANNEL_NAME", "app-builder").strip()
    skip_cleanup = os.environ.get("CRONJOB_SKIP_CLEANUP", "").strip() == "1"

    if not token:
        print("ERROR: DISCORD_BOT_TOKEN must be set.", file=sys.stderr)
        return 1
    if not cron_channel_id:
        print("ERROR: CRONJOB_CHANNEL_ID must be set.", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    try:
        channel = _get_channel(cron_channel_id, headers)
        guild_id = channel.get("guild_id", "")
        print(f"Cron channel: #{channel.get('name')} ({cron_channel_id}) "
              f"in guild {guild_id}")

        # Idempotent: clear any existing schedules panel in the cron channel,
        # then post + pin a fresh one.
        cleared = _remove_schedule_panels(cron_channel_id, headers)
        if cleared:
            print(f"Cleared {cleared} stale schedules panel(s) in the cron channel.")
        message_id = _post_panel(cron_channel_id, build_schedules_panel(), headers)
        _pin(cron_channel_id, message_id, headers)
        print(f"Posted + pinned schedules panel ({message_id}) to the cron channel.")

        # Remove the legacy schedules panel from #app-builder.
        if not skip_cleanup and guild_id:
            ab_id = _find_channel(guild_id, app_builder_name, headers)
            if ab_id:
                removed = _remove_schedule_panels(ab_id, headers)
                print(f"Removed {removed} schedules panel(s) from "
                      f"#{app_builder_name} ({ab_id}).")
            else:
                print(f"#{app_builder_name} not found — nothing to clean up.")
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}",
              file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print("OK — schedules panel now lives in the cron-job channel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
