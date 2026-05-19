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

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture
def discord_id_to_email():
    """The default Discord-ID → email map used in tests."""
    return {"100": "alice@example.com", "200": "bob@example.com"}
