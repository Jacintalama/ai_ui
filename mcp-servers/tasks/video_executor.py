"""VideoRenderExecutor — renders the slideshow MP4 on the build host over SSH.

Mirrors ``RemoteExecutor``'s transport exactly (same ``AGENT_HOST`` /
``AGENT_USER`` / ``AGENT_SSH_KEY_PATH`` env vars, same ``_SSH_OPTS`` /
``_RSYNC_SSH`` options, same ``shlex.quote`` discipline for remote paths, same
rsync exit-code tolerance, same two-attempt back-pull). Two deliberate
differences from the app-build executor:

  1. the rsync-back sanity check looks for **out.mp4**, not ``index.html``;
  2. ``_cleanup_remote`` runs in a **finally** on *every* outcome (success,
     exception, timeout) — a render leaves heavy intermediates (voice.wav,
     caption PNGs, screenshots) on the host that must not accumulate.

Pipeline (heavy steps all run on the host; commands are built as argv lists or
remote shell strings of ``shlex.quote``d PATHS only — no user-supplied text
ever crosses a shell):

  1. in-container prep: render caption PNGs (Pillow) + write ``narration.txt``
  2. mkdir the remote workdir, then rsync the local ``.video/<job_id>/`` dir up
  3. voice on the host: Piper reads ``narration.txt`` -> ``voice.wav`` -> ffmpeg
     transcodes -> ``voice.mp3``
  4. render on the host: ffmpeg argv from ``video_render.build_render_script``
     (host paths), bounded by ``asyncio.timeout``
  5. rsync ``out.mp4`` back to the local workdir (artifact must be out.mp4)
  6. finally: ``rm -rf`` the remote workdir (best-effort)
"""
from __future__ import annotations

import asyncio
import os
import shlex

from claude_executor import CLAUDE_WORKSPACE
from video_render import build_render_script, render_all_captions, resolution_size

# Piper voice model installed on the host by scripts/provision_agent_vm.sh.
_PIPER_BIN = "/opt/piper/piper"
_PIPER_VOICE = "/opt/piper/voices/en_US-amy-medium.onnx"


def _apps_base() -> str:
    """Apps base dir — identical to ``routes_video._apps_dir()`` / video_worker.

    Uploaded screenshots live under ``<apps_base>/<slug>/.video/<job_id>/``, so
    the executor must resolve the same root to find them and write back out.mp4.
    """
    return os.environ.get("APPS_DIR") or os.path.join(CLAUDE_WORKSPACE, "apps")


class VideoRenderExecutor:
    """Render one VideoJob's MP4 on the build host. One ``render()`` per job."""

    # Same SSH discipline as RemoteExecutor — see remote_executor.py for the
    # rationale on each option (BatchMode/accept-new/known_hosts in /tmp).
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

    # ------- public API ----------------------------------------------

    async def render(self, slug: str, job_id: str, plan: dict) -> str:
        """Render ``plan``'s MP4 on the host and return the LOCAL out.mp4 path.

        Raises ``RuntimeError`` on any transport/render failure. The remote
        workdir is always cleaned up in the ``finally`` block.
        """
        host = os.environ["AGENT_HOST"]
        user = os.environ.get("AGENT_USER", "claude-agent")
        key = os.environ["AGENT_SSH_KEY_PATH"]

        local_workdir = os.path.join(_apps_base(), slug, ".video", str(job_id))
        remote_workdir = f"/agent/work/{job_id}"

        # 1. In-container prep: caption PNGs (Pillow) + narration text file.
        size = resolution_size(plan)
        render_all_captions(plan, local_workdir, size)
        narration_path = os.path.join(local_workdir, "narration.txt")
        with open(narration_path, "w", encoding="utf-8") as f:
            f.write(plan.get("narration_script") or "")

        try:
            # 2. Push the prepped workdir up (screenshots/, captions/,
            #    narration.txt) into a fresh remote workdir.
            await self._mkdir_remote(host, user, key, remote_workdir)
            await self._rsync_up(host, user, key, local_workdir, remote_workdir)

            # 3. Voice on the host: Piper (fed narration.txt) -> voice.wav,
            #    then ffmpeg -> voice.mp3.
            await self._voice(host, user, key, remote_workdir)

            # 4. Render on the host (ffmpeg), bounded by a render timeout.
            try:
                async with asyncio.timeout(
                    int(os.environ.get("VIDEO_RENDER_TIMEOUT", "600"))
                ):
                    await self._render_remote(
                        host, user, key, remote_workdir, plan
                    )
            except TimeoutError as exc:
                raise RuntimeError(
                    "video render timed out after "
                    f"{os.environ.get('VIDEO_RENDER_TIMEOUT', '600')}s"
                ) from exc

            # 5. Pull out.mp4 back (sanity-checks the artifact is out.mp4).
            await self._rsync_back(host, user, key, remote_workdir, local_workdir)
            return os.path.join(local_workdir, "out.mp4")
        finally:
            # 6. ALWAYS clean the host workdir — success, error, or timeout.
            await self._cleanup_remote(host, user, key, remote_workdir)

    # ------- helpers ------------------------------------------------

    async def _mkdir_remote(
        self, host: str, user: str, key: str, remote_workdir: str
    ) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}",
            f"mkdir -p {shlex.quote(remote_workdir)}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await proc.wait()
        if rc != 0:
            err = (await proc.stderr.read()).decode() if proc.stderr else ""
            raise RuntimeError(f"remote mkdir exit {rc}: {err[:200]}")

    async def _rsync_up(
        self, host: str, user: str, key: str,
        local_workdir: str, remote_workdir: str,
    ) -> None:
        # Trailing slashes copy the *contents* of the local workdir into the
        # remote workdir. rsync exit 23 (partial transfer) is tolerated, as in
        # RemoteExecutor._push_state.
        src = f"{local_workdir.rstrip('/')}/"
        dst = f"{user}@{host}:{remote_workdir.rstrip('/')}/"
        rs = await asyncio.create_subprocess_exec(
            "rsync", "-az", "--delete",
            "-e", f"{self._RSYNC_SSH} -i {key}",
            src, dst,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await rs.wait()
        if rc not in (0, 23):  # 23 = partial transfer, tolerated
            err = (await rs.stderr.read()).decode() if rs.stderr else ""
            raise RuntimeError(f"push rsync exit {rc}: {err[:200]}")

    async def _voice(
        self, host: str, user: str, key: str, remote_workdir: str
    ) -> None:
        # Piper reads the narration from the rsynced file (stdin redirect),
        # NOT a shell-interpolated string — no user text crosses the shell.
        # Every token is a fixed binary path or a shlex.quote'd remote path.
        wav = f"{remote_workdir}/voice.wav"
        mp3 = f"{remote_workdir}/voice.mp3"
        narration = f"{remote_workdir}/narration.txt"
        remote_cmd = (
            f"{shlex.quote(_PIPER_BIN)} "
            f"-m {shlex.quote(_PIPER_VOICE)} "
            f"-f {shlex.quote(wav)} "
            f"< {shlex.quote(narration)} "
            f"&& ffmpeg -y -i {shlex.quote(wav)} {shlex.quote(mp3)}"
        )
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await proc.wait()
        if rc != 0:
            err = (await proc.stderr.read()).decode() if proc.stderr else ""
            raise RuntimeError(f"voice synthesis exit {rc}: {err[:200]}")

    async def _render_remote(
        self, host: str, user: str, key: str,
        remote_workdir: str, plan: dict,
    ) -> None:
        # build_render_script is called with the HOST workdir so every path in
        # the argv is the host's. The argv is built from the validated plan +
        # host paths only; we shlex.quote each element so no element can break
        # out of the remote shell (defence in depth — captions are baked into
        # PNGs, so no user text reaches the argv in the first place).
        argv = build_render_script(plan, remote_workdir)
        remote_cmd = " ".join(shlex.quote(a) for a in argv)
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-i", key, *self._SSH_OPTS,
            f"{user}@{host}", remote_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        rc = await proc.wait()
        if rc != 0:
            err = (await proc.stderr.read()).decode() if proc.stderr else ""
            raise RuntimeError(f"ffmpeg render exit {rc}: {err[:200]}")

    async def _rsync_back(
        self, host: str, user: str, key: str,
        remote_workdir: str, local_workdir: str,
    ) -> None:
        # Pull ONLY out.mp4 back (the intermediates stay on the host and get
        # cleaned in the finally). Two-attempt retry shape mirrors
        # RemoteExecutor._rsync_back.
        src = f"{user}@{host}:{remote_workdir.rstrip('/')}/out.mp4"
        dst = f"{local_workdir.rstrip('/')}/out.mp4"
        rc = -1
        rs = None
        for _attempt in range(2):
            rs = await asyncio.create_subprocess_exec(
                "rsync", "-az", "--chmod=F644",
                "-e", f"{self._RSYNC_SSH} -i {key}",
                src, dst,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            rc = await rs.wait()
            if rc == 0:
                # Sanity check: the pulled artifact is out.mp4 (NOT index.html
                # — the deliberate divergence from the app-build executor).
                if not os.path.exists(dst):
                    raise RuntimeError("rsync ok but out.mp4 missing")
                return
            await asyncio.sleep(1)
        err = (await rs.stderr.read()).decode() if rs and rs.stderr else ""
        raise RuntimeError(f"rsync-back exit {rc}: {err[:200]}")

    async def _cleanup_remote(
        self, host: str, user: str, key: str, remote_workdir: str
    ) -> None:
        # Best-effort: never raises (called from render()'s finally on every
        # outcome). Heavy intermediates must never accumulate on the box.
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh", "-i", key, *self._SSH_OPTS,
                f"{user}@{host}",
                f"rm -rf {shlex.quote(remote_workdir)}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass
