"""VideoRenderExecutor — host MP4 render over SSH+rsync.

Fully offline: ``asyncio.create_subprocess_exec`` is mocked so no ssh / rsync /
piper / ffmpeg ever runs and no remote host is contacted. ``render_all_captions``
(Pillow) and the narration-file write are patched, and ``os.path.exists`` is
stubbed, so no real disk is touched either.

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

    monkeypatch.setattr("os.path.exists", lambda _p: True)
    with patch("video_executor.render_all_captions", lambda *a, **k: []), \
         patch("video_executor.open", mock_open(), create=True), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = VideoRenderExecutor()
        out_path = await ex.render("myapp", "job-1", _plan())

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
async def test_cleanup_runs_on_failure(monkeypatch):
    calls = []

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        # The host ffmpeg render fails (rc=1); every other step succeeds.
        rc = 1 if _classify(args) == "render" else 0
        return _fake_proc(rc)

    monkeypatch.setattr("os.path.exists", lambda _p: True)
    with patch("video_executor.render_all_captions", lambda *a, **k: []), \
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
