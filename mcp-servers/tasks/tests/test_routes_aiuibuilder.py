# mcp-servers/tasks/tests/test_routes_aiuibuilder.py
"""User-scoped one-shot build endpoint (/api/aiuibuilder)."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import routes_aiuibuilder as rb

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


def test_slugify_basic():
    assert rb._slugify("A Todo List With Dark Mode") == "a-todo-list-with-dark"


def test_slugify_strips_punctuation_and_empty_fallback():
    assert rb._slugify("!!!  ") == "app"
    assert rb._slugify("My App!!! v2") == "my-app-v2"


def test_make_slug_has_suffix_and_matches_route_regex():
    s = rb._make_slug("Todo List")
    assert s.startswith("todo-list-")
    assert _SLUG_RE.match(s)
    assert re.search(r"-[0-9a-f]{4}$", s)


def test_public_build_status_mapping():
    assert rb._public_build_status("completed") == "completed"
    assert rb._public_build_status("failed") == "failed"
    for s in ("running", "planning", "awaiting_input", "pending"):
        assert rb._public_build_status(s) == "running"


def test_preview_url_shape():
    assert rb._preview_url("todo-a1b2") == (
        "https://ai-ui.coolestdomain.win/tasks/preview-app/todo-a1b2/"
    )
