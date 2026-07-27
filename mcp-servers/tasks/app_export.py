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
