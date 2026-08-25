"""Shared fixtures for webhook-handler tests.

Pattern matches mcp-servers/tasks/tests: stub env vars BEFORE the app
is imported anywhere in this test session.
"""
import os
import sys

# Stub required env vars before any test imports webhook-handler modules.
os.environ.setdefault("DISCORD_PUBLIC_KEY", "00" * 32)
os.environ.setdefault("DISCORD_APPLICATION_ID", "1")
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("TASKS_URL", "http://tasks-test:8210")
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-123")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# discord.ext.voice_recv is an optional dependency and is not installed here.
# Several test modules stub it with sys.modules.setdefault so their own
# transitive imports survive, and an EMPTY stub is strictly worse than the
# package being absent: voice_bot.py guards the import with try/except
# ImportError, so absence sets HAS_VOICE_RECV to False and everything is fine,
# while an empty module makes that import SUCCEED and voice_bot then subclasses
# voice_recv.AudioSink at class definition time and dies with AttributeError.
#
# That made the whole suite uncollectable: the stubbing files sort before the
# voice tests, setdefault means first writer wins, and each voice test still
# passed alone. A suite that cannot be collected is a safety net nobody can use.
#
# Fixing it here rather than in each stubbing file, because conftest is imported
# before any test module, so this stub wins and every later setdefault is a
# no-op. If the real package is ever installed, this does nothing.
try:  # pragma: no cover - depends on what is installed
    import discord.ext.voice_recv  # noqa: F401
except Exception:  # noqa: BLE001 - genuinely absent, so give it what is used
    import types

    _vr = types.ModuleType("discord.ext.voice_recv")

    class _AudioSink:  # what voice_bot subclasses
        pass

    class _VoiceRecvClient:  # what voice_bot passes as connect(cls=...)
        pass

    _vr.AudioSink = _AudioSink
    _vr.VoiceRecvClient = _VoiceRecvClient
    sys.modules.setdefault("discord.ext.voice_recv", _vr)

import pytest


@pytest.fixture
def discord_id_to_email():
    """The default Discord-ID → email map used in tests."""
    return {"100": "alice@example.com", "200": "bob@example.com"}


@pytest.fixture(autouse=True)
def _reset_cli_rate_limits():
    """The terminal endpoint's limiters are module-level, so without this the
    tests share one budget and whichever test runs 31st gets a 429 that has
    nothing to do with what it is checking."""
    try:
        import main
    except Exception:  # noqa: BLE001 - tests that never import main are fine
        yield
        return
    main._CLI_PER_IP._hits.clear()
    main._CLI_PER_DEVICE._hits.clear()
    yield
