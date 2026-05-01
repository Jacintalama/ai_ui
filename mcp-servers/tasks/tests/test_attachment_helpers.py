"""Tests for attachment helpers in routes_tasks.

These run pure-Python — no DB, no app. Just helpers."""
import pytest


def test_safe_filename_strips_path_components():
    from routes_tasks import _safe_filename
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("/abs/path/file.png") == "file.png"
    assert _safe_filename("C:\\Windows\\file.png") == "file.png"


def test_safe_filename_keeps_extension():
    from routes_tasks import _safe_filename
    assert _safe_filename("screenshot.png") == "screenshot.png"


def test_safe_filename_rejects_empty_and_dotfiles():
    from routes_tasks import _safe_filename
    assert _safe_filename("") == "unnamed"
    assert _safe_filename("...") == "unnamed"
    # Dotfile-ish: no stem, only extension
    assert _safe_filename(".hidden") == "unnamed.hidden" or _safe_filename(".hidden") == "hidden"


def test_safe_filename_collapses_dangerous_chars():
    from routes_tasks import _safe_filename
    out = _safe_filename("hello world!@#$.png")
    assert out.endswith(".png")
    assert "/" not in out and "\\" not in out and ".." not in out


def test_sniff_image_mime_png():
    from routes_tasks import _sniff_image_mime
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert _sniff_image_mime(png) == "image/png"


def test_sniff_image_mime_jpeg():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"


def test_sniff_image_mime_webp():
    from routes_tasks import _sniff_image_mime
    riff = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 4
    assert _sniff_image_mime(riff) == "image/webp"


def test_sniff_image_mime_gif():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"GIF89a" + b"\x00" * 6) == "image/gif"
    assert _sniff_image_mime(b"GIF87a" + b"\x00" * 6) == "image/gif"


def test_sniff_image_mime_rejects_other():
    from routes_tasks import _sniff_image_mime
    assert _sniff_image_mime(b"%PDF-1.4" + b"\x00" * 4) is None
    assert _sniff_image_mime(b"\x00" * 12) is None
