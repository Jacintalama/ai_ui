import pytest
from pydantic import ValidationError

from models import Schedule
from routes_schedules import CreateScheduleIn, _validate_kind


def test_schedule_model_has_kind_and_video_config_columns():
    cols = Schedule.__table__.columns
    assert "kind" in cols
    assert cols["kind"].server_default.arg == "agent"
    assert cols["kind"].nullable is False
    assert "video_config" in cols
    assert cols["video_config"].nullable is True


def test_create_in_defaults_to_agent():
    body = CreateScheduleIn(name="n", cron_expr="* * * * *", prompt="p")
    assert body.kind == "agent"
    assert body.video_config is None


def test_validate_kind_rejects_unknown():
    with pytest.raises(Exception):
        _validate_kind("banana", None)


def test_validate_kind_video_requires_http_url():
    with pytest.raises(Exception):
        _validate_kind("video", {})
    with pytest.raises(Exception):
        _validate_kind("video", {"url": "ftp://x"})
    _validate_kind("video", {"url": "https://example.com"})  # no raise


def test_validate_kind_agent_ignores_config():
    _validate_kind("agent", None)  # no raise
