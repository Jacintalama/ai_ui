"""Constants for the gateway dedupe fix.

The per-bot dedupe key ensures that two users' bots can emit the same update_id
without a message vanishing as a duplicate. The real coverage is in
test_gateway_bot_route.py::test_two_bots_can_emit_the_same_update_id, which
drives the route-level behavior. This module checks only that the shared bot has
a key of its own.
"""
import main


def test_the_shared_bot_has_a_key_of_its_own():
    assert main.SHARED_BOT_KEY
    assert isinstance(main.SHARED_BOT_KEY, str)
