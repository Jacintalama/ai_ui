"""VideoRenderExecutor — host MP4 render over SSH+rsync.

Fully offline: ``asyncio.create_subprocess_exec`` is mocked so no ssh / rsync /
piper / ffmpeg ever runs and no remote host is contacted. ``render_all_captions``
+ ``render_cards`` (Pillow) and the narration-file write are patched, and
``os.path.exists`` is stubbed, so no real disk is touched either.

These mirror ``test_remote_executor.py``: a fake spawn records every argv and
returns a MagicMock process with ``wait()``/``stderr.read()`` coroutines.
"""
import asyncio  # noqa: F401  (kept for parity with the module under test)
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from video_executor import VideoRenderExecutor


def _plan() -> dict:
    return {
        "template_id": "product_demo",
        "title": "Demo",
        "scenes": [
            {"screenshot": "screenshot-1.png", "caption": "First",
             "duration_s": 3.0, "transition": "crossfade"},
            {"screenshot": "screenshot-2.png", "caption": "Second",
             "duration_s": 2.5, "transition": "cut"},
        ],
        "narration_script": "Hello there. This is the demo.",
        "resolution": "720p",
    }


def _fake_proc(returncode: int = 0):
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.returncode = returncode
    return proc


def _classify(args: tuple) -> str:
    """Identify which transport call an `asyncio.create_subprocess_exec` argv is.

    rsync is disambiguated by direction: the back-pull's *source* (args[-2]) is
    the remote (``user@host:.../out.mp4``), the up-push's source is local.
    """
    cmd = args[0]
    if cmd == "rsync":
        src = args[-2]
        return "rsync_back" if "@" in src else "rsync_up"
    if cmd == "ssh":
        last = args[-1]
        if last.startswith("mkdir -p"):
            return "mkdir"
        if last.startswith("rm -rf"):
            return "cleanup"
        if "/opt/piper/piper" in last:
            return "voice"
        if "ffmpeg" in last and "out.mp4" in last:
            return "render"
    return "other"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    # Same env vars RemoteExecutor reads. user@host contains an '@' so the
    # rsync direction classifier above can tell up-push from back-pull.
    monkeypatch.setenv("AGENT_HOST", "agent-host")
    monkeypatch.setenv("AGENT_USER", "claude-agent")
    monkeypatch.setenv("AGENT_SSH_KEY_PATH", "/tmp/fake_key")
    monkeypatch.setenv("APPS_DIR", "/srv/apps")


@pytest.mark.asyncio
async def test_render_runs_steps_in_order_and_returns_path(monkeypatch):
    calls = []

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        return _fake_proc(0)

    rc_mock = MagicMock()
    monkeypatch.setattr("os.path.exists", lambda _p: True)
    with patch("video_executor.render_all_captions", lambda *a, **k: []), \
         patch("video_executor.render_cards", rc_mock), \
         patch("video_executor.open", mock_open(), create=True), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = VideoRenderExecutor()
        out_path = await ex.render("myapp", "job-1", _plan())

    # Intro/outro cards are rendered in the in-container prep with the plan,
    # the job's local workdir, and the resolved 720p size.
    rc_mock.assert_called_once()
    card_args = rc_mock.call_args.args
    assert card_args[0]["title"] == "Demo"
    assert "job-1" in card_args[1]
    assert card_args[2] == (1280, 720)

    kinds = [_classify(c) for c in calls]
    # Every heavy step happened.
    assert "rsync_up" in kinds
    assert "voice" in kinds
    assert "render" in kinds
    assert "rsync_back" in kinds
    assert "cleanup" in kinds
    # Ordering: prep up before render; voice before render; render before
    # pull-back; cleanup is the final call.
    assert kinds.index("rsync_up") < kinds.index("render")
    assert kinds.index("voice") < kinds.index("render")
    assert kinds.index("render") < kinds.index("rsync_back")
    assert kinds.index("rsync_back") < kinds.index("cleanup")
    assert kinds.index("cleanup") == len(kinds) - 1
    # Returns the LOCAL out.mp4 path under the job's .video dir.
    assert out_path.endswith("out.mp4")
    assert "job-1" in out_path


@pytest.mark.asyncio
async def test_style_is_injected_into_plan_for_every_builder(monkeypatch):
    """The job's style must reach the caption renderer, the cards, AND the
    remote ffmpeg builder as one and the same plan["style"]. This is the exact
    captions-vs-ffmpeg desync the design is most exposed to, so lock it: render
    with an explicit style and assert all three consumers see it."""
    captured = {}

    async def fake_spawn(*args, **kwargs):
        return _fake_proc(0)

    caps_mock = MagicMock(return_value=[])
    cards_mock = MagicMock(return_value=None)

    def fake_build(plan, workdir, *a, **k):
        captured["remote_plan"] = plan
        return ["ffmpeg", "-y", f"{workdir}/out.mp4"]

    monkeypatch.setattr("os.path.exists", lambda _p: True)
    with patch("video_executor.render_all_captions", caps_mock), \
         patch("video_executor.render_cards", cards_mock), \
         patch("video_executor.build_render_script", fake_build), \
         patch("video_executor.open", mock_open(), create=True), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = VideoRenderExecutor()
        await ex.render("myapp", "job-1", _plan(), style="cinematic")

    # The remote ffmpeg builder receives the injected style via plan["style"]...
    assert captured["remote_plan"]["style"] == "cinematic"
    # ...and so do the in-container caption + card renderers.
    assert caps_mock.call_args.args[0]["style"] == "cinematic"
    assert cards_mock.call_args.args[0]["style"] == "cinematic"


@pytest.mark.asyncio
async def test_render_uses_selected_voice_model(monkeypatch):
    """The chosen voice id must resolve to its allowlisted Piper model in the
    on-host synthesis command; an unknown/None voice falls back to the default."""
    async def run(voice):
        calls = []

        async def fake_spawn(*args, **kwargs):
            calls.append(args)
            return _fake_proc(0)

        monkeypatch.setattr("os.path.exists", lambda _p: True)
        with patch("video_executor.render_all_captions", lambda *a, **k: []), \
             patch("video_executor.render_cards", lambda *a, **k: None), \
             patch("video_executor.build_render_script",
                   lambda *a, **k: ["ffmpeg", "-y", "wd/out.mp4"]), \
             patch("video_executor.open", mock_open(), create=True), \
             patch("asyncio.create_subprocess_exec",
                   AsyncMock(side_effect=fake_spawn)):
            ex = VideoRenderExecutor()
            await ex.render("myapp", "job-1", _plan(), voice=voice)
        voice_call = next(c for c in calls if _classify(c) == "voice")
        return " ".join(str(a) for a in voice_call)

    assert "en_GB-alan-medium.onnx" in await run("alan")
    assert "en_US-amy-medium.onnx" in await run(None)        # default
    assert "en_US-amy-medium.onnx" in await run("bogus")     # unknown -> default


@pytest.mark.asyncio
async def test_cleanup_runs_on_failure(monkeypatch):
    calls = []

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        # The host ffmpeg render fails (rc=1); every other step succeeds.
        rc = 1 if _classify(args) == "render" else 0
        return _fake_proc(rc)

    monkeypatch.setattr("os.path.exists", lambda _p: True)
    with patch("video_executor.render_all_captions", lambda *a, **k: []), \
         patch("video_executor.render_cards", lambda *a, **k: None), \
         patch("video_executor.open", mock_open(), create=True), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = VideoRenderExecutor()
        with pytest.raises(RuntimeError):
            await ex.render("myapp", "job-1", _plan())

    kinds = [_classify(c) for c in calls]
    assert "render" in kinds              # render was attempted
    assert "cleanup" in kinds             # finally cleanup STILL ran
    assert kinds[-1] == "cleanup"         # ...and it ran last
    assert "rsync_back" not in kinds      # never reached the pull-back


@pytest.mark.asyncio
async def test_artifact_check_is_out_mp4(monkeypatch):
    calls = []
    checked = []

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        return _fake_proc(0)

    def fake_exists(p):
        checked.append(p)
        return True

    monkeypatch.setattr("os.path.exists", fake_exists)
    with patch("video_executor.render_all_captions", lambda *a, **k: []), \
         patch("video_executor.render_cards", lambda *a, **k: None), \
         patch("video_executor.open", mock_open(), create=True), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = VideoRenderExecutor()
        await ex.render("myapp", "job-1", _plan())

    # The rsync-back pulls out.mp4 (NOT index.html — the deliberate divergence
    # from the app-build executor).
    back = next(c for c in calls if _classify(c) == "rsync_back")
    assert any("out.mp4" in str(a) for a in back)
    assert not any("index.html" in str(a) for a in back)
    # And the post-rsync sanity check verifies out.mp4 on local disk.
    assert any(str(p).endswith("out.mp4") for p in checked)
    assert not any("index.html" in str(p) for p in checked)
