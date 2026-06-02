"""Create (or reuse) the Slack App Builder channel and post its button panel.

Slack analog of scripts/setup_app_builder_channel.py. Idempotent: re-running
reuses a channel with the same name and posts a fresh, re-pinned panel.

Usage:
    SLACK_BOT_TOKEN=xoxb-... \
    [SLACK_APP_BUILDER_CHANNEL=app-builder] \
    [TASKS_URL=http://tasks:8210] [APP_BUILDER_SETUP_EMAIL=admin@example.com] \
    python scripts/setup_slack_app_builder_channel.py

The Slack app needs scopes: channels:read, channels:manage (or groups:write),
chat:write, pins:write, and channels:join to auto-join a public channel.
"""
import os
import sys

import httpx

# Import the pure panel builder from the webhook-handler package.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "webhook-handler"))
from handlers.slack_app_builder_panel import build_panel_blocks, PANEL_TEXT  # noqa: E402

SLACK_API = "https://slack.com/api"


def _fetch_templates(tasks_url: str, email: str) -> list[dict]:
    url = f"{tasks_url.rstrip('/')}/api/aiuibuilder/templates"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers={"X-User-Email": email})
        r.raise_for_status()
    return r.json()


def _slack_get(client: httpx.Client, method: str, token: str, params: dict) -> dict:
    r = client.get(
        f"{SLACK_API}/{method}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    r.raise_for_status()
    return r.json()


def _slack_post(client: httpx.Client, method: str, token: str, body: dict) -> dict:
    r = client.post(
        f"{SLACK_API}/{method}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
    )
    r.raise_for_status()
    return r.json()


def _find_channel(client: httpx.Client, token: str, name: str) -> str | None:
    cursor = ""
    while True:
        params = {"types": "public_channel", "limit": 200, "exclude_archived": True}
        if cursor:
            params["cursor"] = cursor
        data = _slack_get(client, "conversations.list", token, params)
        if not data.get("ok"):
            raise RuntimeError(f"conversations.list: {data.get('error')}")
        for ch in data.get("channels", []):
            if ch.get("name") == name:
                return ch["id"]
        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return None


def _create_channel(client: httpx.Client, token: str, name: str) -> str:
    data = _slack_post(client, "conversations.create", token, {"name": name})
    if not data.get("ok"):
        raise RuntimeError(f"conversations.create: {data.get('error')}")
    return data["channel"]["id"]


def _join_channel(client: httpx.Client, token: str, channel_id: str) -> None:
    # Best-effort: the bot must be a member to post. Ignore "already in channel".
    data = _slack_post(client, "conversations.join", token, {"channel": channel_id})
    if not data.get("ok") and data.get("error") not in ("already_in_channel", "method_not_supported_for_channel_type"):
        print(f"WARN: conversations.join: {data.get('error')}", file=sys.stderr)


def _post_panel(client: httpx.Client, token: str, channel_id: str, blocks: list[dict]) -> str:
    data = _slack_post(client, "chat.postMessage", token, {
        "channel": channel_id,
        "blocks": blocks,
        "text": "AIUI App Builder — pick a template to start.",
    })
    if not data.get("ok"):
        raise RuntimeError(f"chat.postMessage: {data.get('error')}")
    return data["ts"]


def _pin(client: httpx.Client, token: str, channel_id: str, ts: str) -> None:
    data = _slack_post(client, "pins.add", token, {"channel": channel_id, "timestamp": ts})
    if not data.get("ok") and data.get("error") != "already_pinned":
        print(f"WARN: pins.add: {data.get('error')}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    tasks_url = os.environ.get("TASKS_URL", "http://tasks:8210").strip()
    email = os.environ.get("APP_BUILDER_SETUP_EMAIL", "").strip()
    if not email:
        admins = os.environ.get("ADMIN_EMAILS", "").strip()
        email = admins.split(",")[0].strip() if admins else ""
    channel_name = os.environ.get("SLACK_APP_BUILDER_CHANNEL", "app-builder").strip()

    if not token:
        print("ERROR: SLACK_BOT_TOKEN must be set.", file=sys.stderr)
        return 1
    if not email:
        print("ERROR: set APP_BUILDER_SETUP_EMAIL (or ADMIN_EMAILS) to fetch the catalog.",
              file=sys.stderr)
        return 1

    try:
        templates = _fetch_templates(tasks_url, email)
    except Exception as e:
        print(f"ERROR: could not fetch templates from {tasks_url}: {e}", file=sys.stderr)
        return 2
    if not templates:
        print("ERROR: template catalog is empty.", file=sys.stderr)
        return 2

    blocks = build_panel_blocks(templates)

    try:
        with httpx.Client(timeout=30.0) as client:
            channel_id = _find_channel(client, token, channel_name)
            if channel_id:
                print(f"Reusing existing channel #{channel_name} ({channel_id})")
            else:
                channel_id = _create_channel(client, token, channel_name)
                print(f"Created channel #{channel_name} ({channel_id})")
            _join_channel(client, token, channel_id)
            ts = _post_panel(client, token, channel_id, blocks)
            _pin(client, token, channel_id, ts)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Slack API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK — panel posted ({len(templates)} templates) and pinned.")
    print(f"Channel ID: {channel_id}  Message ts: {ts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
