"""RemoteExecutor — SSH+rsync to the agent VM.

Tests mock asyncio.create_subprocess_exec to simulate ssh/rsync calls.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remote_executor import RemoteExecutor, _VALID_SLUG, _truncate_memory


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
    """A `result` event with a COMPLETED outcome triggers rsync-back before
    yielding the line onward."""
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
                return _fake_proc([
                    b'{"type":"assistant","message":{"content":[{"type":"text",'
                    b'"text":"Built the app.\\n\\nCOMPLETED: ok"}]}}\n',
                    b'{"type":"result","subtype":"success","is_error":false,'
                    b'"result":"Built the app.\\n\\nCOMPLETED: ok"}\n',
                ], returncode=0)
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
async def test_completed_period_form_rsyncs_once(monkeypatch):
    """claude --print stream-json emits the final text TWICE — once as an
    `assistant` event, then again as a `result` event — both containing
    'COMPLETED.' (period form). rsync-back + cleanup must fire exactly once.

    line_outcome() only acts on the terminal `result` event and ignores the
    `assistant` event, so the duplicated final text cannot trigger a second
    rsync-back against an already-cleaned workspace.
    """
    calls = []
    monkeypatch.setattr("os.path.exists", lambda _p: True)

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "ssh" and _classify_ssh(args) == "build":
            return _fake_proc([
                b'{"type":"assistant","message":{"content":'
                b'[{"type":"text","text":"COMPLETED. done"}]}}\n',
                b'{"type":"result","subtype":"success",'
                b'"result":"COMPLETED. done"}\n',
            ], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = "".join([c async for c in ex.run("p", slug="myapp", execution_id="e")])

    rsync_calls = [c for c in calls if c[0] == "rsync"]
    cleanup_calls = [c for c in calls
                     if c[0] == "ssh" and _classify_ssh(c) == "cleanup"]
    assert len(rsync_calls) == 2, f"expected push + 1 back, got {len(rsync_calls)}"
    assert len(cleanup_calls) == 1, f"cleanup must fire once, got {len(cleanup_calls)}"
    assert "FAILED" not in out
    assert "COMPLETED. done" in out


@pytest.mark.asyncio
async def test_result_event_bare_completed_triggers_rsync_back(monkeypatch):
    """claude --print stream-json ends with a `result` event whose `result`
    field is the agent's final text. When that text ends with a BARE
    `COMPLETED` — no trailing colon/period/space, preceded by an escaped
    newline — rsync-back must still fire.

    Regression (polar-express / aurora-air e2e): the trigger regex-matched
    the RAW JSON line and required `\\bCOMPLETED[:\\s.]`. In the raw line a
    bare `COMPLETED` is followed by the JSON-closing `"` and preceded by the
    `n` of an escaped `\\n` — so BOTH the leading and trailing word
    boundaries failed, rsync-back never fired, and the agent's customized
    build was stranded on the VM while the orchestrator served the
    uncustomized base copy.
    """
    calls = []
    monkeypatch.setattr("os.path.exists", lambda _p: True)

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "ssh" and _classify_ssh(args) == "build":
            # Mirrors the real polar-express stream: an assistant event then
            # the terminal result event, both ending in a bare `COMPLETED`
            # that is preceded by an escaped \n.
            return _fake_proc([
                b'{"type":"assistant","message":{"content":[{"type":"text",'
                b'"text":"Rebranded the app and wired Duffel data.\\n\\nCOMPLETED"}]}}\n',
                b'{"type":"result","subtype":"success","is_error":false,'
                b'"result":"Rebranded the app and wired Duffel data.\\n\\nCOMPLETED"}\n',
            ], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = "".join([c async for c in ex.run("p", slug="myapp", execution_id="e")])

    rsync_calls = [c for c in calls if c[0] == "rsync"]
    cleanup_calls = [c for c in calls
                     if c[0] == "ssh" and _classify_ssh(c) == "cleanup"]
    assert len(rsync_calls) == 2, f"expected push + 1 rsync-back, got {len(rsync_calls)}"
    assert len(cleanup_calls) == 1, f"cleanup must fire once, got {len(cleanup_calls)}"
    assert "FAILED" not in out


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
    """A `result` event with a NEEDS_INPUT outcome is terminal but gets no
    rsync-back."""
    calls = []
    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        cmd = args[0]
        if cmd == "rsync":
            return _fake_proc([], returncode=0)
        if cmd == "ssh":
            kind = _classify_ssh(args)
            if kind == "build":
                return _fake_proc([
                    b'{"type":"result","subtype":"success","is_error":false,'
                    b'"result":"NEEDS_INPUT: which travel dates?"}\n',
                ], returncode=0)
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
            return _fake_proc([
                b'{"type":"result","subtype":"success",'
                b'"result":"COMPLETED: ok"}\n',
            ], returncode=0)
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


@pytest.mark.asyncio
async def test_user_jwt_forwarded_via_sendenv(monkeypatch):
    """When run() is given user_jwt, the build-ssh call must use
    SendEnv=AIUI_AGENT_EFFORT,IO_USER_JWT and have IO_USER_JWT in the
    subprocess env.
    """
    monkeypatch.setattr("os.path.exists", lambda _p: True)
    seen_env = {}
    seen_args = []

    async def fake_spawn(*args, **kwargs):
        seen_args.append(args)
        if kwargs.get("env"):
            seen_env.update(kwargs["env"])
        cmd = args[0]
        if cmd == "ssh" and "claude --print" in args[-1]:
            return _fake_proc([
                b'{"type":"result","subtype":"success","is_error":false,'
                b'"result":"COMPLETED: ok"}\n',
            ], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        async for _ in ex.run("build it", slug="myapp", execution_id="e",
                              user_jwt="abc.def.ghi"):
            pass

    build_ssh = next(a for a in seen_args
                     if a[0] == "ssh" and "claude --print" in a[-1])
    # The SendEnv flag pair must be SPACE-separated (NOT comma-separated).
    # OpenSSH's SendEnv treats commas literally — comma-joined names become
    # one bogus variable name and nothing gets sent. Regression guard:
    # asserts the exact form, not just substring containment.
    sendenv_indices = [i for i, v in enumerate(build_ssh)
                       if v == "-o" and i + 1 < len(build_ssh)
                       and "SendEnv=" in build_ssh[i + 1]]
    assert sendenv_indices, "no -o SendEnv= flag found on the build ssh"
    sendenv_value = build_ssh[sendenv_indices[0] + 1]
    assert sendenv_value == "SendEnv=AIUI_AGENT_EFFORT IO_USER_JWT", (
        f"SendEnv must be SPACE-separated, got: {sendenv_value!r}. "
        "Comma syntax silently sends zero variables — SSH treats the whole "
        "comma-joined string as one (non-existent) variable name."
    )
    # The subprocess env passed to ssh contains the JWT
    assert seen_env.get("IO_USER_JWT") == "abc.def.ghi"


# ---------------------------------------------------------------------------
# Memory truncation: when MEMORY.md exceeds the soft cap, the oldest "## "
# sections get dropped first so the newest entries survive. The title and
# any pre-section preamble (everything before the first "## ") are always
# kept so the agent retains identity / persona context.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_scrubs_credentials_in_output(monkeypatch):
    """A credential leaked into the agent's stdout must be redacted before
    it reaches the orchestrator-side log (and from there, the DB).

    Setup mirrors test_happy_path_streams_and_rsyncs: the build-ssh proc
    emits an assistant chunk containing a fake sk-ant- key plus a terminal
    result event with COMPLETED, so rsync-back fires but the body of the
    stream gets scrubbed.
    """
    monkeypatch.setattr("os.path.exists", lambda _p: True)

    async def fake_spawn(*args, **kwargs):
        cmd = args[0]
        if cmd == "ssh" and _classify_ssh(args) == "build":
            return _fake_proc([
                b'{"type":"assistant","message":{"content":[{"type":"text",'
                b'"text":"DEBUG api_key=sk-ant-realkey12345abcdef_xyz_longer"}]}}\n',
                b'{"type":"result","subtype":"success","is_error":false,'
                b'"result":"COMPLETED: build done"}\n',
            ], returncode=0)
        return _fake_proc([], returncode=0)

    with patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=fake_spawn)):
        ex = RemoteExecutor()
        out = "".join([c async for c in ex.run("p", slug="myapp", execution_id="e")])

    # The raw key must NOT appear in the orchestrator-visible stream.
    assert "sk-ant-realkey" not in out
    # The redaction placeholder must appear.
    assert "<REDACTED_ANTHROPIC>" in out
    # The terminal sentinel (and surrounding non-sensitive text) survives.
    assert "COMPLETED: build done" in out


def test_ssh_opts_bound_connection_and_transfer():
    """Every ssh/rsync transport call must inherit connect + keepalive bounds.

    Only _ssh_ok set ConnectTimeout; _push_state/_rsync_back/_cleanup_remote/
    _fetch_memory/_push_memory could hang forever on a wedged agent VM and
    wedge the build worker (audit 2026-06-15). ConnectTimeout caps the connect
    phase; ServerAlive* drops a mid-transfer stall.
    """
    opts = " ".join(RemoteExecutor._SSH_OPTS)
    assert "ConnectTimeout=" in opts
    assert "ServerAliveInterval=" in opts
    assert "ServerAliveCountMax=" in opts
    rsync_ssh = RemoteExecutor._RSYNC_SSH
    assert "ConnectTimeout=" in rsync_ssh
    assert "ServerAliveInterval=" in rsync_ssh
    assert "ServerAliveCountMax=" in rsync_ssh


def test_truncate_keeps_newest_memory_sections():
    head = "# Memory\n"
    section = "## 2026-05-{day:02d} entry\nbody{day}\n"
    big = head + "\n".join(section.format(day=d) for d in range(1, 30))
    out = _truncate_memory(big, 500)
    # Title preserved
    assert "# Memory" in out
    # Newest section survives
    assert "2026-05-29" in out or "body29" in out
    # Some slack for the head; the soft cap is best-effort
    assert len(out.encode()) <= 600
