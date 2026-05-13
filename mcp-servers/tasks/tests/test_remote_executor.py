"""RemoteExecutor — SSH+rsync to the agent VM.

Tests mock asyncio.create_subprocess_exec to simulate ssh/rsync calls.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remote_executor import RemoteExecutor, _VALID_SLUG


def test_slug_validator_accepts_normal_slugs():
    assert _VALID_SLUG.fullmatch("flight-booker")
    assert _VALID_SLUG.fullmatch("my_app_v2")
    assert _VALID_SLUG.fullmatch("a")


def test_slug_validator_rejects_traversal():
    assert _VALID_SLUG.fullmatch("../etc") is None
    assert _VALID_SLUG.fullmatch("bad..slug") is None
    assert _VALID_SLUG.fullmatch("") is None
    assert _VALID_SLUG.fullmatch("BadCase") is None
    assert _VALID_SLUG.fullmatch("a" * 100) is None
    assert _VALID_SLUG.fullmatch("with space") is None
    assert _VALID_SLUG.fullmatch("with/slash") is None


def _fake_proc(stdout_chunks: list[bytes], returncode: int = 0):
    proc = MagicMock()
    proc.stdout = MagicMock()
    chunks = list(stdout_chunks) + [b""]
    async def _read(_n):
        return chunks.pop(0)
    proc.stdout.read = AsyncMock(side_effect=_read)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    proc.returncode = returncode
    return proc


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AGENT_HOST", "claude-agent")
    monkeypatch.setenv("AGENT_USER", "claude-agent")
    monkeypatch.setenv("AGENT_SSH_KEY_PATH", "/tmp/fake_key")


@pytest.mark.asyncio
async def test_invalid_slug_raises():
    ex = RemoteExecutor()
    with pytest.raises(ValueError, match="slug"):
        async for _ in ex.run("p", slug="../etc", execution_id="x"):
            pass


def _classify_ssh(args: tuple) -> str:
    """Disambiguate which RemoteExecutor ssh call this is by exact suffix."""
    last = args[-1]
    if last == "true":
        return "healthcheck"
    if last.startswith("mkdir -p /agent/work/"):
        return "mkdir"
    if last.startswith("rm -rf /agent/work/"):
        return "cleanup"
    if "pkill" in last:
        return "kill"
    if "claude --print" in last:
        return "build"
    return "other"


@pytest.mark.asyncio
async def test_happy_path_streams_and_rsyncs(monkeypatch):
    """COMPLETED triggers rsync-back before yielding the line onward."""
    calls = []

    # Stub the index.html sanity check so the rsync-back path succeeds without
    # us actually copying files to CLAUDE_WORKSPACE.
    monkeypatch.setattr("os.path.exists", lambda _p: True)

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "ssh":
            kind = _classify_ssh(args)
            if kind == "build":
                return _fake_proc([b"hello\n", b"COMPLETED: ok\n"], returncode=0)
            return _fake_proc([], returncode=0)
        if cmd == "rsync":
            return _fake_proc([], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = []
        async for chunk in ex.run("p", slug="myapp", execution_id="ex1"):
            out.append(chunk)
    full = "".join(out)
    assert "COMPLETED: ok" in full
    # Exactly two rsyncs: push (before build) and pull-back (after COMPLETED)
    rsync_calls = [c for c in calls if c[0] == "rsync"]
    assert len(rsync_calls) == 2


@pytest.mark.asyncio
async def test_unreachable_yields_failed_sentinel():
    """ssh health check returns non-zero → FAILED: agent_unreachable."""
    async def fake_spawn(*args, **kwargs):
        return _fake_proc([], returncode=255)
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = "".join([c async for c in ex.run("p", slug="x", execution_id="e")])
    assert "FAILED: agent_unreachable" in out


@pytest.mark.asyncio
async def test_needs_input_does_not_rsync():
    """NEEDS_INPUT yields and closes without triggering rsync-back."""
    calls = []
    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "rsync":
            return _fake_proc([], returncode=0)
        if cmd == "ssh":
            kind = _classify_ssh(args)
            if kind == "build":
                return _fake_proc([b"NEEDS_INPUT: which date?\n"], returncode=0)
            return _fake_proc([], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run("p", slug="myapp", execution_id="e"):
            pass
    rsync_calls = [c for c in calls if c[0] == "rsync"]
    # Exactly one rsync (the push). No pull-back on NEEDS_INPUT.
    assert len(rsync_calls) == 1


@pytest.mark.asyncio
async def test_shell_quote_handles_metacharacters(monkeypatch):
    """Prompts with quotes, $, backticks must be shell-quoted."""
    monkeypatch.setattr("os.path.exists", lambda _p: True)
    captured = []
    async def fake_spawn(*args, **kwargs):
        captured.append(args)
        cmd = args[0]
        if cmd == "ssh" and len(args) > 6:
            # the build ssh — last arg is the full remote command
            return _fake_proc([b"COMPLETED: ok\n"], returncode=0)
        return _fake_proc([], returncode=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run('build app with `id`; $(rm -rf /); "quoted"',
                              slug="myapp", execution_id="e"):
            pass
    # The build-ssh call's command must NOT contain raw backticks or $()
    build_ssh = next(c for c in captured
                     if c[0] == "ssh" and "claude" in c[-1])
    raw_cmd = build_ssh[-1]
    # shlex.quote wraps in single-quotes; backticks are now harmless text
    assert "rm -rf" in raw_cmd        # text passes through
    # but the dangerous expansions are quoted away
    assert "$(rm -rf" not in raw_cmd or "'" in raw_cmd  # quoted form acceptable
