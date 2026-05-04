"""Tests for the file-tree filter in routes_preview.

The Files tab calls /api/tasks/<id>/files which walks apps/<slug>/. Without a
filter, internal directories like .attachments/ (chat image uploads) leak into
the user-facing tree. This module verifies the filter excludes them.
"""
from routes_preview import _should_include_path


def test_filter_excludes_attachments_anywhere_in_path():
    assert _should_include_path((".attachments", "abc-task-id", "image.png")) is False
    assert _should_include_path(("subdir", ".attachments", "x.png")) is False


def test_filter_excludes_node_modules():
    assert _should_include_path(("node_modules", "react", "index.js")) is False
    assert _should_include_path(("packages", "node_modules", "x.js")) is False


def test_filter_keeps_normal_app_files():
    assert _should_include_path(("index.html",)) is True
    assert _should_include_path(("src", "main.js")) is True
    assert _should_include_path(("styles", "main.css")) is True


def test_filter_keeps_user_dotfiles():
    """The user's own .gitignore / .env are NOT internal — keep them visible."""
    assert _should_include_path((".gitignore",)) is True
    assert _should_include_path((".env.example",)) is True
