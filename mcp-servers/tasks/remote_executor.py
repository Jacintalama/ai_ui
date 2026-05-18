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
    line_outcome,
)
from secret_scrub import scrub as _scrub_stream


_VALID_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")


def _truncate_memory(text: str, max_bytes: int) -> str:
    """Soft-cap MEMORY.md by dropping the OLDEST `## ` sections first.

    Anything before the first `## ` (title + preamble — the agent's persona
    context) is always preserved. Sections are split on a leading `\\n## `,
    so a section starts at the literal characters `## ` on a new line.
    Best-effort: the cap is honored only if there is at least one section
    we can drop; otherwise we return the head intact (even if it exceeds
    max_bytes — we will not mangle the agent's identity to hit a number).
    """
    parts = text.split("\n## ", 1)
    if len(parts) == 1:
        # No sections — just the title/preamble. Return as-is even if oversized.
        return text
    head = parts[0]
    # Re-split the section body so each entry starts with "## " literally.
    # Splitting "2026-05-01 entry\n...\n## 2026-05-02 entry\n..." on "\n## "
    # yields ["2026-05-01 entry\n...", "2026-05-02 entry\n...", ...]; we re-
    # prefix each with "## " so concatenation reproduces the original.
    raw_sections = parts[1].split("\n## ")
    sections = ["## " + s for s in raw_sections]
    # Drop oldest sections until we fit (head + remaining sections).
    while sections and (
        len(head.encode()) + sum(len(("\n" + s).encode()) for s in sections) > max_bytes
    ):
        sections.pop(0)
    if not sections:
        return head
    return head + "\n" + "\n".join(sections)


class RemoteExecutor:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    # ------- public API ----------------------------------------------

    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
        user_jwt: str | None = None,
        schedule_id: str | None = None,
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

        # 3a. If this is a scheduled run, fetch MEMORY.md into the workdir.
        # The agent reads it at the top of the run; we'll push back the
        # mutated version after a successful completion. Failure to fetch
        # is soft — we surface a sentinel but continue so a one-off
        # transient SSH glitch doesn't break the whole heartbeat.
        if schedule_id and slug:
            try:
                await self._fetch_memory(host, user, key, schedule_id, slug)
            except RuntimeError as e:
                yield f"[memory fetch failed: {e}]\n"

        # 4. Build + spawn the remote command
        remote_cmd = self._build_remote_cmd(prompt, slug, effort)
        try:
            async for line in self._stream(host, user, key, remote_cmd,
                                           user_jwt=user_jwt):
                # 5. claude --print --verbose emits exactly one terminal
                # `result` event, last. line_outcome() decodes it — raw-line
                # regex matching is unreliable because an escaped \n before,
                # or the JSON-closing " after, a sentinel keyword breaks
                # regex word boundaries. On `completed`, rsync the agent
                # workspace back BEFORE yielding the line so the
                # orchestrator's /files lookup succeeds after parsing.
                outcome = line_outcome(line)
                if outcome is not None:
                    # Scheduler runs: push MEMORY.md back on ANY terminal
                    # outcome (the agent may have written useful state even
                    # if it didn't produce the COMPLETED sentinel). App-build
                    # runs: only rsync back on completed (the existing flow).
                    if schedule_id and slug:
                        try:
                            await self._push_memory(
                                host, user, key, schedule_id, slug,
                            )
                        except RuntimeError as e:
                            yield f"[memory push failed: {e}]\n"
                    if outcome.kind == "completed" and slug:
                        try:
                            if not schedule_id:
                                await self._rsync_back(host, user, key, slug)
                            await self._cleanup_remote(host, user, key, slug)
                        except RuntimeError as e:
                            yield f"FAILED: transport_error {e}\n"
                            return
                    # The result event is terminal regardless of outcome —
                    # NEEDS_INPUT / NEEDS_STEPS / FAILED get no rsync-back.
                    yield line
                    return
                yield line
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

    async def _stream(self, host: str, user: str, key: str, remote_cmd: str,
                      user_jwt: str | None = None) -> AsyncIterator[str]:
        # SSH SendEnv is SPACE-separated, not comma-separated. With a comma
        # OpenSSH treats the whole string as a single (non-existent) variable
        # name and silently sends nothing. Same applies to sshd_config's
        # AcceptEnv on the receiving side. (Diagnosed 2026-05-15 after a smoke
        # showed IO_USER_JWT never reached the agent VM despite this code
        # appearing correct.)
        sendenv = "AIUI_AGENT_EFFORT"
        env_pass = None
        if user_jwt:
            sendenv = "AIUI_AGENT_EFFORT IO_USER_JWT"
            env_pass = {**os.environ, "IO_USER_JWT": user_jwt}
        self._proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            "-o", f"SendEnv={sendenv}",
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env_pass,
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
                            # Final partial line — scrub before yielding.
                            yield _scrub_stream(buf.decode("utf-8", errors="replace"))
                        break
                    if bytes_yielded >= MAX_LOG_BYTES:
                        self._proc.kill()
                        yield "\n[OUTPUT CAP exceeded — process killed]\n"
                        break
                    bytes_yielded += len(chunk)
                    buf += chunk
                    while b"\n" in buf:
                        line, _, buf = buf.partition(b"\n")
                        # Scrub every line we yield. line_outcome() then
                        # parses scrubbed text — safe because COMPLETED:/
                        # FAILED:/NEEDS_INPUT: sentinels can't overlap any
                        # credential pattern in secret_scrub.
                        yield _scrub_stream(
                            line.decode("utf-8", errors="replace")
                        ) + "\n"
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

    # ------- per-schedule MEMORY.md roundtrip -------------------------

    async def _fetch_memory(
        self, host: str, user: str, key: str, schedule_id: str, slug: str,
    ) -> None:
        """Copy /agent/memory/<schedule_id>.md → /agent/work/<slug>/MEMORY.md.

        If the source file doesn't exist yet (first run for this schedule),
        we initialize an empty file remotely so the cp succeeds and the
        agent always sees a MEMORY.md at the workdir root.
        """
        qsid = shlex.quote(schedule_id)
        qslug = shlex.quote(slug)
        cmd = (
            "mkdir -p /agent/memory && "
            f"touch /agent/memory/{qsid}.md && "
            f"cp /agent/memory/{qsid}.md /agent/work/{qslug}/MEMORY.md"
        )
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}", cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await proc.wait()
        if rc != 0:
            err = (await proc.stderr.read()).decode() if proc.stderr else ""
            raise RuntimeError(f"memory fetch exit {rc}: {err[:200]}")

    async def _push_memory(
        self, host: str, user: str, key: str, schedule_id: str, slug: str,
    ) -> None:
        """Read MEMORY.md off the agent, scrub it, truncate to 50KB, write
        it back atomically (.tmp → mv) into /agent/memory/<id>.md.

        Reading via `cat` (rather than rsync-pull) lets us hold the entire
        contents in process memory for scrubbing without ever staging the
        un-scrubbed bytes on local disk. The atomic mv ensures concurrent
        readers always see a complete file.
        """
        from secret_scrub import scrub as _scrub
        qsid = shlex.quote(schedule_id)
        qslug = shlex.quote(slug)
        cat_proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            f"cat /agent/work/{qslug}/MEMORY.md",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        raw, _ = await cat_proc.communicate()
        if cat_proc.returncode != 0:
            # No memory written this run — fine, nothing to persist.
            return
        scrubbed = _scrub(raw.decode("utf-8", errors="replace"))
        if len(scrubbed.encode()) > 50_000:
            scrubbed = _truncate_memory(scrubbed, 50_000)
        push_proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            f"cat > /agent/memory/{qsid}.md.tmp && "
            f"mv /agent/memory/{qsid}.md.tmp /agent/memory/{qsid}.md",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err_bytes = await push_proc.communicate(scrubbed.encode())
        if push_proc.returncode != 0:
            err = err_bytes.decode() if err_bytes else ""
            raise RuntimeError(f"memory push exit {push_proc.returncode}: {err[:200]}")

    async def _kill_remote(self, host: str, user: str, key: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            'pkill -u claude-agent -f "claude --print" || true',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
