"""Build-ready card now has a 4th button: a 'Visual Editor' link with a
slug-bound signed token."""
import os
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

from handlers.app_builder_panel import build_ready_components
from handlers.visual_edit_token import verify_edit_token


def _flat(rows):
    return [c for row in rows for c in row["components"]]


def test_visual_edit_button_present():
    rows = build_ready_components("my-slug", "https://preview.example/x",
                                  owner="ralph@example.com")
    labels = [c.get("label", "") for c in _flat(rows)]
    assert any("Visual Editor" in lbl for lbl in labels)


def test_visual_edit_url_carries_signed_slug_token():
    rows = build_ready_components("my-slug", "https://preview.example/x",
                                  owner="ralph@example.com")
    btn = next(c for c in _flat(rows) if "Visual Editor" in c.get("label", ""))
    assert btn["style"] == 5  # LINK
    url = btn["url"]
    assert url.startswith("https://")
    assert "/tasks/edit/my-slug" in url
    # Extract ?token=... and verify it round-trips to the owner + slug.
    from urllib.parse import urlparse, parse_qs
    token = parse_qs(urlparse(url).query)["token"][0]
    assert verify_edit_token(token, "my-slug") == "ralph@example.com"


def test_owner_required():
    """Without an owner we cannot sign; the function must require it."""
    import pytest
    with pytest.raises(TypeError):
        build_ready_components("my-slug", "https://preview.example/x")
