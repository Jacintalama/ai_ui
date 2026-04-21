"""Manage preview subprocesses for built apps.

Supports three app flavors, in this priority order:
  1. Node project   — package.json with a `dev` or `start` script that runs node
  2. Python project — server.py / main.py / app.py at the app root
  3. Static site    — index.html at the app root (served via `npx serve`)

Whichever matches first, we run it with PORT=9100 so the Caddy preview-app
route (which proxies to tasks:9100) picks it up.
"""
import asyncio
import json
import logging
import os
import shlex
import time

logger = logging.getLogger("tasks.preview")

WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")
PREVIEW_PORT_START = 9100
IDLE_TIMEOUT = 1800  # 30 minutes

_current: dict | None = None

PYTHON_ENTRY_CANDIDATES = ("server.py", "main.py", "app.py")


def _resolve_command(app_dir: str, port: int) -> tuple[str, str]:
    """Figure out how to start the app. Returns (kind, shell_command).

    kind is one of "node" | "python" | "static" so logs can tell which branch ran.
    """
    pkg_json_path = os.path.join(app_dir, "package.json")
    requirements_path = os.path.join(app_dir, "requirements.txt")
    python_entry = next(
        (f for f in PYTHON_ENTRY_CANDIDATES if os.path.isfile(os.path.join(app_dir, f))),
        None,
    )
    index_html = os.path.join(app_dir, "index.html")

    # ── 1. Node project ───────────────────────────────────────────────────────
    if os.path.isfile(pkg_json_path):
        try:
            with open(pkg_json_path) as f:
                pkg = json.load(f)
        except Exception as exc:
            logger.warning("package.json parse failed: %s", exc)
            pkg = {}
        scripts: dict = pkg.get("scripts") or {}
        dev_cmd = scripts.get("dev") or ""
        start_cmd = scripts.get("start") or ""

        # If the npm scripts call python, treat this as a Python project.
        scripts_are_python = (
            "python" in dev_cmd.lower() or "python" in start_cmd.lower()
        )
        if not scripts_are_python and ("dev" in scripts or "start" in scripts):
            script_name = "dev" if "dev" in scripts else "start"
            return (
                "node",
                f"cd {shlex.quote(app_dir)} && "
                f"npm install --silent --no-audit --no-fund && "
                f"PORT={port} npm run {script_name}",
            )

    # ── 2. Python project ─────────────────────────────────────────────────────
    if python_entry:
        parts = [f"cd {shlex.quote(app_dir)}"]
        if os.path.isfile(requirements_path):
            parts.append("pip install -q -r requirements.txt")
        else:
            # Heuristic: if the entry imports flask and it's not installed, grab it.
            # Cheap no-op when flask is already importable.
            parts.append(
                "(python3 -c 'import flask' 2>/dev/null || pip install -q flask)"
            )
        parts.append(f"PORT={port} python3 {shlex.quote(python_entry)}")
        return ("python", " && ".join(parts))

    # ── 3. Static site ────────────────────────────────────────────────────────
    if os.path.isfile(index_html):
        return (
            "static",
            f"npx --yes serve -s {shlex.quote(app_dir)} -l {port} --no-clipboard",
        )

    raise FileNotFoundError(
        f"Cannot determine how to run apps/{os.path.basename(app_dir)}/ — "
        "no runnable npm script, server.py/main.py/app.py, or index.html"
    )


async def start_preview(slug: str) -> int:
    global _current
    await stop_preview()

    app_dir = os.path.join(WORKSPACE, "apps", slug)
    if not os.path.isdir(app_dir):
        raise FileNotFoundError(f"App directory not found: apps/{slug}/")

    port = PREVIEW_PORT_START
    kind, cmd = _resolve_command(app_dir, port)

    logger.info("Preview starting: slug=%s kind=%s port=%d", slug, kind, port)
    logger.info("Preview command: %s", cmd)

    # start_new_session=True puts the subprocess in its own process group
    # so we can kill the whole tree (npm → node → serve, or sh → python) on stop.
    proc = await asyncio.create_subprocess_exec(
        "sh", "-c", cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )

    _current = {
        "slug": slug,
        "port": port,
        "proc": proc,
        "kind": kind,
        "started": time.time(),
    }
    logger.info("Preview started: %s (kind=%s, pid=%d)", slug, kind, proc.pid)
    return port


async def stop_preview() -> None:
    """Kill the whole process group (npm -> node -> serve child chain)."""
    global _current
    if _current is None:
        return
    proc = _current["proc"]
    try:
        # Kill the whole process group so child serve/node don't orphan.
        os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
        await proc.wait()
    except (ProcessLookupError, PermissionError):
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
        "kind": _current.get("kind"),
        "running": _current["proc"].returncode is None,
        "elapsed_seconds": int(elapsed),
    }
