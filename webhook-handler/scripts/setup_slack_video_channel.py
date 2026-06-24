"""Post the Slack Video Studio panel into #video-generation.

One-shot setup. Idempotent: re-running posts a fresh panel. The bot must
already be a member of the target channel; if the post fails with
not_in_channel, invite the bot to the channel first.

Usage (in the repo):
    SLACK_BOT_TOKEN=xoxb-... \
    [SLACK_VIDEO_CHANNEL_ID=C0BCRE20JNR] \
    python webhook-handler/scripts/setup_slack_video_channel.py [CHANNEL_ID]

Usage (inside the deployed webhook-handler container):
    docker compose -f docker-compose.unified.yml exec \
      webhook-handler python /app/scripts/setup_slack_video_channel.py

Required bot scope: chat:write.
"""
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
from clients.slack import SlackClient  # noqa: E402
from handlers.slack_video_panel import build_video_panel  # noqa: E402

DEFAULT_CHANNEL_ID = "C0BCRE20JNR"


async def main() -> int:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: SLACK_BOT_TOKEN must be set.", file=sys.stderr)
        return 1

    channel_id = (
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("SLACK_VIDEO_CHANNEL_ID", DEFAULT_CHANNEL_ID)
    ).strip()

    panel = build_video_panel()
    slack = SlackClient(bot_token=token)

    ts = await slack.post_message(
        channel_id,
        text="AIUI Video Studio",
        blocks=panel["blocks"],
    )

    if ts is None:
        print(
            f"ERROR: Failed to post panel to channel {channel_id}. "
            "If the error is not_in_channel, invite the bot to the channel "
            "and retry.",
            file=sys.stderr,
        )
        return 3

    print(f"OK -- video panel posted to {channel_id} (ts={ts}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
