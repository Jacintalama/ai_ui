"""render_mode + animation_preset on the draft + model."""
import os

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from routes_video import DraftRequest  # noqa: E402
from video_models import VideoJob  # noqa: E402


def test_draft_request_render_mode_default_and_valid():
    assert DraftRequest().render_mode == "remotion"
    assert DraftRequest(render_mode="animated").render_mode == "animated"
    assert DraftRequest(render_mode="slideshow").render_mode == "slideshow"
    assert DraftRequest(render_mode="remotion").render_mode == "remotion"


def test_draft_request_rejects_unknown_render_mode():
    with pytest.raises(ValidationError):
        DraftRequest(render_mode="claymation")


def test_video_job_has_render_mode_column():
    assert "render_mode" in VideoJob.__table__.columns


def test_draft_request_animation_preset_default_and_valid():
    assert DraftRequest().animation_preset == "cursor_click"
    assert DraftRequest(animation_preset="smooth_scroll").animation_preset == "smooth_scroll"
    assert DraftRequest(animation_preset="spotlight").animation_preset == "spotlight"
    assert DraftRequest(animation_preset="zoom_pan").animation_preset == "zoom_pan"


def test_draft_request_rejects_unknown_animation_preset():
    with pytest.raises(ValidationError):
        DraftRequest(animation_preset="explode_everything")


def test_video_job_has_animation_preset_column():
    col = VideoJob.__table__.c.animation_preset
    assert col.nullable is False
    assert col.default.arg == "cursor_click"
