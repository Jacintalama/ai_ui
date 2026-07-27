"""What analyze_app must see: index presence, Supabase usage, chat-proxy usage.

The chat-proxy flag exists because exported apps CANNOT reach the platform's
LLM proxy; silently shipping a broken AI feature is the failure mode."""
import app_export
from app_export import AppProfile, analyze_app


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_missing_app_returns_none(tmp_path):
    assert analyze_app("nope", apps_root=tmp_path) is None


def test_plain_static_app(tmp_path):
    _write(tmp_path / "shop", "index.html", "<html><body>hi</body></html>")
    _write(tmp_path / "shop", "styles/main.css", "body{}")
    p = analyze_app("shop", apps_root=tmp_path)
    assert p == AppProfile(has_index=True, uses_supabase=False,
                           uses_chat_proxy=False, size_bytes=p.size_bytes,
                           file_count=2)
    assert p.size_bytes > 0


def test_supabase_markers_detected(tmp_path):
    _write(tmp_path / "crm", "index.html", "<html></html>")
    _write(tmp_path / "crm", "src/main.js",
           "const c = supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);")
    assert analyze_app("crm", apps_root=tmp_path).uses_supabase is True


def test_chat_proxy_detected(tmp_path):
    _write(tmp_path / "bot", "index.html", "<html></html>")
    _write(tmp_path / "bot", "app.js", "fetch('/api/chat-proxy', {method:'POST'})")
    assert analyze_app("bot", apps_root=tmp_path).uses_chat_proxy is True


def test_missing_index_is_flagged(tmp_path):
    _write(tmp_path / "raw", "readme.md", "no index here")
    assert analyze_app("raw", apps_root=tmp_path).has_index is False


def test_artifact_dirs_are_not_scanned(tmp_path):
    _write(tmp_path / "a", "index.html", "<html></html>")
    _write(tmp_path / "a", ".attachments/x.js", "window.SUPABASE_URL")
    _write(tmp_path / "a", ".video/y.js", "/api/chat-proxy")
    _write(tmp_path / "a", ".git/config", "[core]")
    p = analyze_app("a", apps_root=tmp_path)
    assert p.uses_supabase is False and p.uses_chat_proxy is False
    assert p.file_count == 1
