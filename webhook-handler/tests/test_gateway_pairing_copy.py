"""The pairing reply is the first thing a new user ever reads from us.

It has to say who we are, what to do, and where, in a message that survives
being read on a phone.
"""
from gateway.pairing import pairing_message

URL = "https://ai-ui.coolestdomain.win/tasks/gateway/link"


def test_the_code_and_the_link_are_both_present():
    msg = pairing_message("ABCD2345", URL)
    assert "ABCD2345" in msg
    assert URL in msg


def test_it_says_the_code_expires():
    assert "hour" in pairing_message("ABCD2345", URL).lower()


def test_no_em_dashes_or_en_dashes():
    # Global writing rule: these are an AI tell and this is copy a person reads.
    msg = pairing_message("ABCD2345", URL)
    assert "—" not in msg and "–" not in msg


def test_it_fits_in_a_single_telegram_message():
    assert len(pairing_message("ABCD2345", URL)) < 900
