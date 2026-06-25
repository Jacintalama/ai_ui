import httpx
import json as _json
import pytest
from video_remotion_client import render_remotion


async def test_render_remotion_posts_and_returns_path():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["json"] = _json.loads(request.content)
        return httpx.Response(200, json={"ok": True,
            "outPath": "/j/remotion-video.mp4", "frames": 90})

    transport = httpx.MockTransport(handler)
    out = await render_remotion("/j", theme="parity", fps=24, width=1280, height=720,
        host="x.com", title="X",
        scenes=[{"kind": "title", "headline": "Hi", "durationS": 2}],
        base_url="http://video-remotion:8090", _transport=transport)
    assert out == "/j/remotion-video.mp4"
    assert captured["url"].endswith("/render")
    body = captured["json"]
    assert body["jobDir"] == "/j"
    assert body["theme"] == "parity"
    assert body["host"] == "x.com"
    assert body["scenes"][0]["headline"] == "Hi"


async def test_render_remotion_raises_on_500():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(500, json={"ok": False, "error": "boom"}))
    with pytest.raises(RuntimeError):
        await render_remotion("/j", theme="parity", fps=24, width=1280, height=720,
            host="", title="",
            scenes=[{"kind": "title", "durationS": 2}],
            base_url="http://x", _transport=transport)


async def test_render_remotion_raises_when_not_ok():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": False, "error": "bad scene"}))
    with pytest.raises(RuntimeError):
        await render_remotion("/j", theme="parity", fps=24, width=1280, height=720,
            host="", title="",
            scenes=[{"kind": "title", "durationS": 2}],
            base_url="http://x", _transport=transport)
