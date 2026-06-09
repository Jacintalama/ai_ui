"""Create (or reuse) the Slack recruiting channel and post its button panel.

One-shot setup. Idempotent: re-running reuses a channel with the same name and
posts a fresh panel. Slack analog of setup_recruiting_channel.py (Discord).

Usage (in the repo):
    SLACK_BOT_TOKEN=xoxb-... \
    [SLACK_RECRUITING_CHANNEL_ID=C0123ABC] \
    [SLACK_RECRUITING_CHANNEL_NAME=recruiting] \
    python webhook-handler/scripts/setup_slack_recruiting_channel.py

Usage (inside the deployed webhook-handler container):
    docker compose -f docker-compose.unified.yml exec \
      webhook-handler python /app/scripts/setup_slack_recruiting_channel.py

Required bot scopes: chat:write, channels:read; channels:manage (to create) and
channels:join (to join) when not given an explicit channel id. If the bot lacks
the create scope, create the channel + invite the bot in Slack and pass
SLACK_RECRUITING_CHANNEL_ID.
"""
import os
import sys

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from handlers.slack_recruiting_panel import build_recruiting_blocks  # noqa: E402

SLACK_API = "https://slack.com/api"


def _call(method: str, token: str, **payload) -> dict:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{SLACK_API}/{method}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            json=payload,
        )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method} failed: {data.get('error')}")
    return data


def _find_channel(token: str, name: str) -> str | None:
    cursor = ""
    while True:
        data = _call("conversations.list", token, types="public_channel",
                     exclude_archived=True, limit=200, cursor=cursor)
        for ch in data.get("channels", []):
            if ch.get("name") == name:
                return ch["id"]
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return None


def main() -> int:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("SLACK_RECRUITING_CHANNEL_ID", "").strip()
    name = os.environ.get("SLACK_RECRUITING_CHANNEL_NAME", "recruiting").strip()

    if not token:
        print("ERROR: SLACK_BOT_TOKEN must be set.", file=sys.stderr)
        return 1

    try:
        if channel_id:
            print(f"Using SLACK_RECRUITING_CHANNEL_ID: {channel_id}")
        else:
            channel_id = _find_channel(token, name)
            if channel_id:
                print(f"Reusing existing #{name} ({channel_id})")
            else:
                data = _call("conversations.create", token, name=name)
                channel_id = data["channel"]["id"]
                print(f"Created #{name} ({channel_id})")
        # Make sure the bot is a member so it can post (no-op if already in).
        try:
            _call("conversations.join", token, channel=channel_id)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: conversations.join: {e}", file=sys.stderr)

        _call("chat.postMessage", token, channel=channel_id,
              blocks=build_recruiting_blocks(),
              text="Recruiting Outreach — find engineers and email them a job.")
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Slack API {e.response.status_code}: {e.response.text}",
              file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK — recruiting panel posted to #{name} ({channel_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
