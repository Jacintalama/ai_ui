"""httpx logs the full request URL at INFO, and Telegram's API requires the bot
token inside that URL. Without this, every save, test, toggle and remove writes
a user's bot token into the container log, which promtail ships to Loki.

webhook-handler hit this first; commit d7e67d9c7 fixed it there. This is the
same guard for the service that actually holds the tokens.
"""
import logging

import main  # noqa: F401  (imported for its logging configuration side effect)


def test_httpx_cannot_log_a_request_url():
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_httpcore_cannot_log_a_request_url():
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
