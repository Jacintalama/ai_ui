"""Manage preview subprocesses for built apps."""
import asyncio
import logging
import os
import time

logger = logging.getLogger("tasks.preview")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
PREVIEW_PORT_START = 9100
IDLE_TIMEOUT = 1800  # 30 minutes

_current: dict | None = None


async def start_preview(slug: str) -> int:
    global _current
    await stop_preview()

    app_dir = os.path.join(WORKSPACE, "apps", slug)
    if not os.path.isdir(app_dir):
        raise FileNotFoundError(f"App directory not found: apps/{slug}/")

    port = PREVIEW_PORT_START
    pkg_json = os.path.join(app_dir, "package.json")

    if os.path.isfile(pkg_json):
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", f"cd {app_dir} && npm install --silent && npm run dev -- --port {port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            "npx", "serve", "-s", app_dir, "-l", str(port), "--no-clipboard",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    _current = {"slug": slug, "port": port, "proc": proc, "started": time.time()}
    logger.info("Preview started: %s on port %d (pid %d)", slug, port, proc.pid)
    return port


async def stop_preview() -> None:
    global _current
    if _current is None:
        return
    proc = _current["proc"]
    try:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass
    logger.info("Preview stopped: %s", _current["slug"])
    _current = None


def get_status() -> dict | None:
    if _current is None:
        return None
    elapsed = time.time() - _current["started"]
    return {
        "slug": _current["slug"],
        "port": _current["port"],
        "pid": _current["proc"].pid,
        "running": _current["proc"].returncode is None,
        "elapsed_seconds": int(elapsed),
    }
