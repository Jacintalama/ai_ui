"""Pure helpers around a user's own bot. No database, no network.

The masking and the allow gate are the two that carry real consequences: one
decides what leaves the server, the other decides who gets to talk to a bot.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import gateway_bots as gb


def test_a_bot_key_is_long_random_hex():
    key = gb.new_bot_key()
    assert len(key) == 32
    assert all(c in "0123456789abcdef" for c in key)


def test_two_bot_keys_are_never_the_same():
    assert gb.new_bot_key() != gb.new_bot_key()


def test_a_webhook_secret_is_its_own_value():
    # Reusing bot_key as the secret would make the public path segment the
    # credential.
    assert gb.new_webhook_secret() != gb.new_bot_key()
    assert len(gb.new_webhook_secret()) == 32


def test_a_token_survives_a_round_trip():
    token = "123456:AAH1234567890abcdefghijklmnopqrs"
    assert gb.decrypt_token(gb.encrypt_token(token)) == token


def test_encrypting_does_not_leave_the_token_readable():
    token = "123456:AAH1234567890abcdefghijklmnopqrs"
    assert token not in gb.encrypt_token(token)


def test_a_masked_token_shows_only_the_last_four():
    assert gb.mask_token("123456:AAH1234567890abcdefghijklmnop4f2a") == "...4f2a"


def test_a_short_token_masks_to_nothing_readable():
    # Never fall back to showing the whole thing when it is short.
    assert gb.mask_token("abc") == "..."


def test_allowed_ids_are_normalized():
    assert gb.parse_allowed_ids(" 111, 222 ,333 ") == "111,222,333"


def test_allowed_ids_drop_anything_that_is_not_a_number():
    # A Telegram user id is numeric. Anything else is a typo or an injection
    # attempt, and silently keeping it would widen the gate.
    assert gb.parse_allowed_ids("111, @someone, 222") == "111,222"


def test_allowed_ids_of_nothing_is_empty():
    assert gb.parse_allowed_ids("  ,  , ") == ""


def test_an_unclaimed_bot_lets_the_first_sender_in():
    assert gb.is_allowed("", None, "999") is True


def test_a_claimed_bot_only_serves_its_claimer():
    assert gb.is_allowed("", "999", "999") is True
    assert gb.is_allowed("", "999", "1000") is False


def test_an_allow_list_overrides_the_claim():
    assert gb.is_allowed("111,222", "999", "222") is True
    assert gb.is_allowed("111,222", "999", "999") is False
