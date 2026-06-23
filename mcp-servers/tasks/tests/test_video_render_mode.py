"""render_mode (slideshow|animated) on the draft + model."""
import os

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

os.environ.setdefault("AIUI_FERNET_KEY", Fernet.generate_key().decode())

from routes_video import DraftRequest  # noqa: E402
from video_models import VideoJob  # noqa: E402


def test_draft_request_render_mode_default_and_valid():
    assert DraftRequest().render_mode == "slideshow"
    assert DraftRequest(render_mode="animated").render_mode == "animated"


def test_draft_request_rejects_unknown_render_mode():
    with pytest.raises(ValidationError):
        DraftRequest(render_mode="claymation")


def test_video_job_has_render_mode_column():
    assert "render_mode" in VideoJob.__table__.columns
