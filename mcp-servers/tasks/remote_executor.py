"""RemoteExecutor — runs claude on a dedicated VM over SSH.

Flow per run:
  1. Validate slug (strict regex; raises ValueError on injection attempts).
  2. Pre-flight: ssh ... true. On non-zero exit → yield FAILED: agent_unreachable.
  3. Push current workspace state to agent VM via rsync (orchestrator-initiated;
     no reverse-direction SSH key needed).
  4. ssh ... claude --print ... — stream stdout line by line.
  5. On COMPLETED: rsync agent VM workspace BACK to orchestrator, then
     yield COMPLETED to the parser, then close. (Order matters — the
     orchestrator's /files lookup must succeed after parsing.)
  6. On NEEDS_INPUT / NEEDS_STEPS / FAILED: yield and close; no rsync-back.
  7. On timeout: pkill remote, yield FAILED: timeout, close.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import AsyncIterator

from claude_executor import (
    EXECUTION_TIMEOUT_SECONDS,
    MAX_LOG_BYTES,
    MAX_PROMPT_CHARS,
    CLAUDE_WORKSPACE,
    _COMPLETED_LINE_RE,
)


_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")


class RemoteExecutor:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    # ------- public API ----------------------------------------------

    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]:
        # 1. Validate slug
        if slug is not None and not _VALID_SLUG.fullmatch(slug):
            raise ValueError(f"invalid slug: {slug!r}")

        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

        host = os.environ["AGENT_HOST"]
        user = os.environ.get("AGENT_USER", "claude-agent")
        key  = os.environ["AGENT_SSH_KEY_PATH"]
        effort = os.environ.get("AIUI_AGENT_EFFORT", "low")

        # 2. Health check
        if not await self._ssh_ok(host, user, key):
            yield "FAILED: agent_unreachable\n"
            return

        # 3. Push current state (no-op if app dir does not yet exist)
        if slug:
            try:
                await self._push_state(host, user, key, slug)
            except RuntimeError as e:
                yield f"FAILED: transport_error {e}\n"
                return

        # 4. Build + spawn the remote command
        remote_cmd = self._build_remote_cmd(prompt, slug, effort)
        try:
            async for line in self._stream(host, user, key, remote_cmd):
                # 5. On COMPLETED line: rsync back BEFORE yielding the line.
                # Uses the same regex as parse_outcome (accepts COMPLETED:,
                # COMPLETED<space>, COMPLETED.) so the trigger stays in sync
                # with the parser.
                if _COMPLETED_LINE_RE.search(line) and slug:
                    try:
                        await self._rsync_back(host, user, key, slug)
                        await self._cleanup_remote(host, user, key, slug)
                    except RuntimeError as e:
                        yield f"FAILED: transport_error {e}\n"
                        return
                yield line
                if self._is_terminal(line):
                    return
        except asyncio.TimeoutError:
            await self._kill_remote(host, user, key)
            yield f"FAILED: timeout after {EXECUTION_TIMEOUT_SECONDS}s\n"

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass

    # ------- helpers ------------------------------------------------

    @staticmethod
    def _is_terminal(line: str) -> bool:
        return any(t in line for t in ("COMPLETED:", "FAILED:", "NEEDS_INPUT:", "NEEDS_STEPS:"))

    # Standard SSH options used by every invocation in this class.
    # BatchMode=yes: never prompt (we're non-interactive).
    # StrictHostKeyChecking=accept-new: trust the host fingerprint on first
    #   connection and remember it. Critical because every container rebuild
    #   wipes /root/.ssh/known_hosts, and BatchMode=yes refuses unknown hosts
    #   without this. UserKnownHostsFile keeps the cache in /tmp so we don't
    #   need /root/.ssh to exist.
    _SSH_OPTS = (
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/tmp/agent_known_hosts",
    )
    _RSYNC_SSH = (
        "ssh -o BatchMode=yes "
        "-o StrictHostKeyChecking=accept-new "
        "-o UserKnownHostsFile=/tmp/agent_known_hosts"
    )

    async def _ssh_ok(self, host: str, user: str, key: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, "-o", "ConnectTimeout=10",
            *self._SSH_OPTS,
            f"{user}@{host}", "true",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        return rc == 0

    async def _push_state(self, host: str, user: str, key: str, slug: str) -> None:
        # Ensure remote workspace dir exists
        mk = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            f"mkdir -p /agent/work/{shlex.quote(slug)}/apps/{shlex.quote(slug)}",
        )
        if await mk.wait() != 0:
            raise RuntimeError("mkdir failed")

        src = f"{CLAUDE_WORKSPACE}/apps/{slug}/"
        dst = f"{user}@{host}:/agent/work/{slug}/apps/{slug}/"
        rs = await asyncio.create_subprocess_exec(
            "rsync", "-az", "--delete",
            "-e", f"{self._RSYNC_SSH} -i {key}",
            src, dst,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await rs.wait()
        if rc not in (0, 23):  # 23 = partial transfer (no src yet), tolerated
            err = (await rs.stderr.read()).decode() if rs.stderr else ""
            raise RuntimeError(f"push rsync exit {rc}: {err[:200]}")

    def _build_remote_cmd(self, prompt: str, slug: str | None, effort: str) -> str:
        # AIUI_AGENT_EFFORT is forwarded from the orchestrator via SSH
        # SendEnv (see _stream below) — the sshd_config on the agent VM
        # AcceptEnv-lists it. We pass --effort explicitly anyway for
        # belt-and-braces (in case SendEnv was filtered en route).
        qprompt = shlex.quote(prompt)
        cwd = "/agent/work" if slug is None else f"/agent/work/{shlex.quote(slug)}"
        # `set -a` auto-exports every variable defined while sourcing ~/.env,
        # so ANTHROPIC_API_KEY actually reaches the claude subprocess. Without
        # this, plain `source` only sets shell locals and the subprocess sees
        # apiKeySource=none → "Not logged in · Please run /login".
        return (
            "set -e; "
            f"cd {cwd}; "
            "set -a; source ~/.env; set +a; "
            "IS_SANDBOX=1 claude --print --dangerously-skip-permissions "
            "--output-format stream-json --verbose "
            f"--effort {shlex.quote(effort)} "
            f"-- {qprompt}"
        )

    async def _stream(self, host: str, user: str, key: str, remote_cmd: str) -> AsyncIterator[str]:
        self._proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            "-o", "SendEnv=AIUI_AGENT_EFFORT",
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert self._proc.stdout is not None
        bytes_yielded = 0
        buf = b""
        try:
            async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
                while True:
                    chunk = await self._proc.stdout.read(4096)
                    if not chunk:
                        if buf:
                            yield buf.decode("utf-8", errors="replace")
                        break
                    if bytes_yielded >= MAX_LOG_BYTES:
                        self._proc.kill()
                        yield "\n[OUTPUT CAP exceeded — process killed]\n"
                        break
                    bytes_yielded += len(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line, _, buf = buf.partition(b"\n")
                        yield line.decode("utf-8", errors="replace") + "\n"
                await self._proc.wait()
        finally:
            self._proc = None

    async def _rsync_back(self, host: str, user: str, key: str, slug: str) -> None:
        src = f"{user}@{host}:/agent/work/{slug}/apps/{slug}/"
        dst = f"{CLAUDE_WORKSPACE}/apps/{slug}/"
        # First attempt, plus one retry
        rc = -1
        rs = None
        for attempt in range(2):
            rs = await asyncio.create_subprocess_exec(
                "rsync", "-az", "--delete", "--chmod=D755,F644",
                "-e", f"{self._RSYNC_SSH} -i {key}",
                src, dst,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            rc = await rs.wait()
            if rc == 0:
                # Sanity check
                if not os.path.exists(os.path.join(dst, "index.html")):
                    raise RuntimeError("rsync ok but index.html missing")
                return
            await asyncio.sleep(1)
        err = (await rs.stderr.read()).decode() if rs and rs.stderr else ""
        raise RuntimeError(f"rsync exit {rc}: {err[:200]}")

    async def _cleanup_remote(self, host: str, user: str, key: str, slug: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            f"rm -rf /agent/work/{shlex.quote(slug)}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()  # best-effort

    async def _kill_remote(self, host: str, user: str, key: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            'pkill -u claude-agent -f "claude --print" || true',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
