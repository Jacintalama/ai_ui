"""Colored embeds for build-ready and published messages."""
from handlers import app_builder_panel as p


def test_build_ready_embed():
    e = p.build_ready_embed("port-ab12", "https://preview", "Your portfolio is ready!")
    assert "ready" in e["title"].lower()
    assert isinstance(e["color"], int)
    assert "portfolio is ready" in e["description"]


def test_build_published_embed():
    e = p.build_published_embed("port-ab12", "https://port-ab12.ai-ui.coolestdomain.win/")
    assert "publish" in e["title"].lower()
    assert "port-ab12" in e["description"]
    assert isinstance(e["color"], int)
