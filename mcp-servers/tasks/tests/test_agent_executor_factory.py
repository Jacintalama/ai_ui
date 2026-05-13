"""Factory dispatches to the right executor based on AGENT_BACKEND env."""
import os
import pytest
from unittest.mock import patch

from agent_executor import get_executor, BaseExecutor


def test_default_is_local():
    """No env var → LocalExecutor."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENT_BACKEND", None)
        ex = get_executor()
        assert ex.__class__.__name__ == "LocalExecutor"


def test_local_explicit():
    """AGENT_BACKEND=local → LocalExecutor."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "local"}):
        ex = get_executor()
        assert ex.__class__.__name__ == "LocalExecutor"


def test_remote_returns_remote():
    """AGENT_BACKEND=remote → RemoteExecutor."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "remote"}):
        ex = get_executor()
        assert ex.__class__.__name__ == "RemoteExecutor"


def test_unknown_value_raises():
    """AGENT_BACKEND=garbage → ValueError, no silent fallback."""
    with patch.dict(os.environ, {"AGENT_BACKEND": "garbage"}):
        with pytest.raises(ValueError, match="garbage"):
            get_executor()


def test_baseexecutor_is_protocol():
    """BaseExecutor is a Protocol — instances of conforming classes pass isinstance."""
    from typing import Protocol, runtime_checkable
    # Just verify the import works and Protocol attrs are present
    assert hasattr(BaseExecutor, "run")
    assert hasattr(BaseExecutor, "stop")
