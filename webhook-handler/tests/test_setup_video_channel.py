import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))


def test_payload_merges_panel_and_embed():
    import setup_video_channel as s
    from handlers.video_panel import build_video_panel, build_video_embed
    payload = {**build_video_panel(), "embeds": [build_video_embed()]}
    assert "components" in payload and payload["embeds"][0]["title"]
    assert s.DISCORD_API.endswith("/v10")
    assert s.TEXT_CHANNEL == 0
