"""What a stranger is told, and whether they can act on it.

Written after Ralph asked the obvious question: how does someone in Slack or
Discord use a code when they have never touched the IO website? They cannot.
The bot sits in a workspace, so a colleague who has never heard of IO can
message it and get back a code plus an instruction to sign in to something they
do not have.
"""
from gateway.pairing import pairing_message

URL = "https://io.example/tasks/gateway/link"


def test_the_code_is_in_the_message():
    assert "ABCD2345" in pairing_message("ABCD2345", URL)


def test_it_says_where_to_put_the_code():
    assert URL in pairing_message("ABCD2345", URL)


def test_it_tells_someone_with_no_account_what_to_do():
    # The whole point. Without this the message is a dead end for anyone who
    # met IO through somebody else's workspace.
    msg = pairing_message("ABCD2345", URL).lower()
    assert "account" in msg
    assert "https://io.example" in msg


def test_the_signup_link_is_the_site_not_the_channels_page():
    # Sending a signed-out person to the Channels page shows them nothing.
    msg = pairing_message("ABCD2345", URL)
    tail = msg.split("New here?")[1]
    assert "https://io.example" in tail
    assert "/tasks/gateway/link" not in tail


def test_it_says_what_io_is():
    # "Sign in to IO" means nothing to someone who has never heard of it.
    assert "assistant" in pairing_message("ABCD2345", URL).lower()


def test_it_still_says_the_code_expires():
    msg = pairing_message("ABCD2345", URL).lower()
    assert "once" in msg and "hour" in msg


def test_a_url_without_the_tasks_prefix_does_not_break_the_signup_line():
    # Defensive: link_url is built from GATEWAY_PUBLIC_URL, which an operator
    # could set to anything.
    msg = pairing_message("ABCD2345", "https://io.example")
    assert "https://io.example" in msg.split("New here?")[1]
