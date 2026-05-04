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
PREVIEW_PORT_MAX = 9119  # 20-port pool for concurrent dynamic previews
IDLE_TIMEOUT = 1800  # 30 minutes

_running: dict[str, dict] = {}  # slug -> {kind, port, proc, started}

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
    # Accept any directory that contains at least one .html file, not just
    # index.html. npx serve will serve the whole directory; users can navigate
    # to the file directly, and when index.html exists it will be served at /.
    has_html = os.path.isfile(index_html) or any(
        f.endswith(".html") for f in os.listdir(app_dir) if os.path.isfile(os.path.join(app_dir, f))
    )
    if has_html:
        return (
            "static",
            f"npx --yes serve -s {shlex.quote(app_dir)} -l {port} --no-clipboard",
        )

    raise FileNotFoundError(
        f"Cannot determine how to run apps/{os.path.basename(app_dir)}/ — "
        "no runnable npm script, server.py/main.py/app.py, or index.html"
    )


def _pick_port() -> int | None:
    used = {info["port"] for info in _running.values() if info.get("port")}
    for p in range(PREVIEW_PORT_START, PREVIEW_PORT_MAX + 1):
        if p not in used:
            return p
    return None


def _url_for(slug: str) -> str:
    """Per-slug preview URL — works for both static and dynamic apps."""
    return f"/tasks/preview-app/{slug}/"


async def start_preview(slug: str) -> dict:
    """Start (or rejoin) the preview for one slug. Per-slug isolation —
    starting one project no longer kills another user's preview.

    Returns: {kind, port, url, slug}. For static apps, port is None and the
    file server is the FastAPI handler at /tasks/preview-app/{slug}/.
    For dynamic apps, port is allocated from a 20-port pool (9100-9119).
    Idempotent — calling twice for the same slug returns the same info.
    """
    # Idempotent: if already registered and still healthy, return it.
    info = _running.get(slug)
    if info is not None:
        proc = info.get("proc")
        if info["kind"] == "static" or (proc is not None and proc.returncode is None):
            return {
                "slug": slug,
                "kind": info["kind"],
                "port": info.get("port"),
                "url": _url_for(slug),
            }
        # Stale entry (process died) — drop it and re-spawn.
        _running.pop(slug, None)

    app_dir = os.path.join(WORKSPACE, "apps", slug)
    if not os.path.isdir(app_dir):
        raise FileNotFoundError(f"App directory not found: apps/{slug}/")

    # Resolve command at port=0 just to detect kind. Static apps don't need
    # a process at all — the FastAPI /tasks/preview-app/{slug}/ route serves
    # the files directly from disk.
    kind, _probe_cmd = _resolve_command(app_dir, 0)
    if kind == "static":
        _running[slug] = {
            "slug": slug,
            "kind": "static",
            "port": None,
            "proc": None,
            "started": time.time(),
        }
        logger.info("Preview ready (static, no spawn): %s", slug)
        return {"slug": slug, "kind": "static", "port": None, "url": _url_for(slug)}

    # Dynamic app — allocate a port from the pool and spawn.
    port = _pick_port()
    if port is None:
        raise RuntimeError(
            f"All preview ports in use ({PREVIEW_PORT_START}-{PREVIEW_PORT_MAX}). "
            "Stop another running preview first."
        )
    _, cmd = _resolve_command(app_dir, port)
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

    _running[slug] = {
        "slug": slug,
        "port": port,
        "proc": proc,
        "kind": kind,
        "started": time.time(),
    }
    logger.info("Preview started: %s (kind=%s, pid=%d, port=%d)", slug, kind, proc.pid, port)
    return {"slug": slug, "kind": kind, "port": port, "url": _url_for(slug)}


async def stop_preview(slug: str | None = None) -> None:
    """Stop one preview by slug, or all of them if slug is None.

    Static apps have no process — popping them from _running is enough.
    Dynamic apps get the whole process group SIGKILLed."""
    if slug is None:
        # Stop everything (used at service shutdown).
        for s in list(_running.keys()):
            await stop_preview(s)
        return

    info = _running.pop(slug, None)
    if info is None:
        return

    proc = info.get("proc")
    if proc is not None:
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL the whole process group
            await proc.wait()
        except (ProcessLookupError, PermissionError):
            pass
    logger.info("Preview stopped: %s (kind=%s)", slug, info.get("kind"))


# Idle-stop sweep — stops previews whose page has had no presence
# heartbeat for PRESENCE_GRACE_SECONDS. Spawned once at app startup.
PRESENCE_GRACE_SECONDS = 120
SWEEP_INTERVAL_SECONDS = 30

_empty_since: dict[str, float] = {}


async def _idle_sweep_loop(is_slug_empty) -> None:
    """Run forever: every SWEEP_INTERVAL_SECONDS, stop previews whose
    presence bucket has been empty for ≥ PRESENCE_GRACE_SECONDS.
    is_slug_empty is injected so this module stays import-free of
    routes_projects."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            now = time.time()
            for slug in list(_running.keys()):
                if is_slug_empty(slug):
                    if slug not in _empty_since:
                        _empty_since[slug] = now
                    elif now - _empty_since[slug] >= PRESENCE_GRACE_SECONDS:
                        logger.info("Auto-stopping idle preview: %s", slug)
                        await stop_preview(slug)
                        _empty_since.pop(slug, None)
                else:
                    _empty_since.pop(slug, None)
            # Evict orphaned timestamps for slugs that exited _running by
            # other paths (manual /preview/stop, subprocess crash). Keeps
            # _empty_since bounded over the process lifetime.
            for stale in [s for s in _empty_since if s not in _running]:
                _empty_since.pop(stale, None)
        except Exception:
            logger.exception("idle sweep iteration failed")


def get_status(slug: str | None = None) -> dict | None:
    """Return status for one slug. If slug is None, returns the first
    running slug for backward-compat (the global slot model is gone)."""
    if slug is None:
        if not _running:
            return None
        slug = next(iter(_running))

    info = _running.get(slug)
    if info is None:
        return None

    elapsed = time.time() - info["started"]
    proc = info.get("proc")
    is_running = info["kind"] == "static" or (proc is not None and proc.returncode is None)
    return {
        "slug": slug,
        "kind": info.get("kind"),
        "port": info.get("port"),
        "pid": proc.pid if proc is not None else None,
        "running": is_running,
        "elapsed_seconds": int(elapsed),
        "url": _url_for(slug),
    }
