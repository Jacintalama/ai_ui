"""Take Your App With You: export bundle + deploy guide.

Spec: docs/superpowers/specs/2026-07-27-app-export-bundle-design.md
User-initiated, so errors SURFACE (unlike the fail-open build sweeps); only the
optional enrichments (history, schema) degrade to README notes."""
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_APPS_ROOT = Path(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")) / "apps"
_SKIP_DIRS = {".git", ".attachments", ".video", "node_modules"}
_TEXT_SUFFIXES = {".html", ".htm", ".js", ".css", ".json", ".md", ".txt"}
_SUPABASE_MARKERS = ("window.SUPABASE", "aiui-config", "createClient(")
_CHAT_PROXY_MARKER = "/api/chat-proxy"


@dataclass(frozen=True)
class AppProfile:
    has_index: bool
    uses_supabase: bool
    uses_chat_proxy: bool
    size_bytes: int
    file_count: int


def _app_files(app_dir: Path):
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            yield Path(root) / name


def analyze_app(slug: str, *, apps_root: Path | None = None) -> AppProfile | None:
    app_dir = (apps_root or _APPS_ROOT) / slug
    if not app_dir.is_dir():
        return None
    uses_supabase = uses_chat_proxy = False
    size = count = 0
    for f in _app_files(app_dir):
        count += 1
        try:
            size += f.stat().st_size
        except OSError:
            continue
        if f.suffix.lower() in _TEXT_SUFFIXES:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not uses_supabase and any(m in text for m in _SUPABASE_MARKERS):
                uses_supabase = True
            if not uses_chat_proxy and _CHAT_PROXY_MARKER in text:
                uses_chat_proxy = True
    return AppProfile(
        has_index=(app_dir / "index.html").is_file(),
        uses_supabase=uses_supabase,
        uses_chat_proxy=uses_chat_proxy,
        size_bytes=size,
        file_count=count,
    )


@dataclass(frozen=True)
class DeployTarget:
    key: str
    name: str
    steps: tuple[str, ...]

    def supports(self, profile: AppProfile) -> tuple[bool, str]:
        # Every IO app today is static files, which every target below hosts.
        # When server-side app types exist, per-target constraints go here
        # (e.g. "Vercel cannot run Docker containers").
        return True, ""


DEPLOY_TARGETS: tuple[DeployTarget, ...] = (
    DeployTarget("github-pages", "GitHub Pages", (
        "Create a new repository on github.com and push this folder to it "
        "(`git remote add origin <url> && git push -u origin main`).",
        "In the repository: Settings, Pages, set Source to `main` branch, root folder.",
        "Your app appears at `https://<user>.github.io/<repo>/` in about a minute.",
    )),
    DeployTarget("netlify", "Netlify", (
        "Go to app.netlify.com and log in (free tier works).",
        "Drag this whole folder onto the Netlify Drop area, or connect the "
        "GitHub repository if you pushed one.",
        "Netlify gives you a live URL immediately; no build settings needed.",
    )),
    DeployTarget("vercel", "Vercel", (
        "Push this folder to a GitHub repository first.",
        "On vercel.com, choose Add New Project and import that repository.",
        "Framework preset: Other. No build command. Output directory: `./`.",
    )),
    DeployTarget("cloudflare-pages", "Cloudflare Pages", (
        "Push this folder to a GitHub repository first.",
        "In the Cloudflare dashboard: Workers & Pages, Create, Pages, "
        "connect the repository.",
        "No build command; leave the output directory as `/`.",
    )),
    DeployTarget("own-server", "Your own server (any static host)", (
        "Copy this folder to the server.",
        "Serve it with any web server, e.g. `python -m http.server 8000` to "
        "test, or point nginx/Caddy at the folder for real hosting.",
    )),
)


def build_deploy_guide(profile: AppProfile) -> str:
    lines = ["## Where this app can run", ""]
    warnings = []
    if profile.uses_chat_proxy:
        warnings.append(
            "- **AI features will not work after export.** This app calls the IO "
            "platform's `/api/chat-proxy`, which only exists on IO. Standalone, "
            "those requests fail; you would need your own backend and API key.")
    if profile.uses_supabase:
        warnings.append(
            "- This app uses Supabase. The bundle's `aiui-config.js` must contain "
            "your project URL and anon key (see the Database section below).")
    if warnings:
        lines += ["### Before you deploy", *warnings, ""]
    for t in DEPLOY_TARGETS:
        ok, reason = t.supports(profile)
        lines.append(f"### {t.name}")
        if not ok:
            lines += [f"Not supported for this app: {reason}", ""]
            continue
        lines += [f"{i}. {s}" for i, s in enumerate(t.steps, 1)]
        lines.append("")
    return "\n".join(lines)
