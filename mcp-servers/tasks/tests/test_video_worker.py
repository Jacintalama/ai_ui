"""Unit tests for the video worker loop skeleton.

The full stage dispatch is filled in Phase 3; here we only pin down the
kill-switch behavior of `_should_run`, which is a pure read of the
`VIDEO_ENABLED` env var (default-on).
"""
import pytest

from video_worker import _should_run


def test_should_run_respects_kill_switch(monkeypatch):
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    assert _should_run() is False
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    assert _should_run() is True
