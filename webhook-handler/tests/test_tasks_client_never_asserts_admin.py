"""The Discord/Slack tasks client must never send X-User-Admin.

A regression pin, not a fix: the behaviour is already correct and is left
exactly as it is. What was missing was anything that would notice if someone
"fixed" the asymmetry it produces — an admin scheduling from Discord is capped
while the same person is exempt on the web — by adding the header here.

That asymmetry is the price of the header being trustworthy at all. The tasks
service trusts X-User-Admin because the API gateway strips it from the client
request and re-sets it only after validating the JWT, so a client cannot assert
it. The webhook-handler is not the gateway: it resolves an email from a Discord
or Slack identity and holds no JWT. If it sent the header, the header would
become forgeable-by-proxy and every route in the tasks service that reads it
would be weakened — to buy an admin a cap they can already bypass through the
web UI or the operator secret.

`CLAUDE.md`: "When adding a feature whose correctness lives in a prompt, treat
it as unimplemented until something asserts the outcome." The same applies to
one that lives in a comment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients.tasks import TasksClient  # noqa: E402


def _client():
    return TasksClient("http://tasks:8210", internal_secret="not-the-cron-secret")


def test_the_user_scoped_headers_are_exactly_the_email():
    assert _client()._headers("someone@example.com") == {
        "X-User-Email": "someone@example.com"
    }


def test_no_admin_header_is_ever_sent():
    """The whole point. Case-insensitive: HTTP header names are, and a
    lowercase spelling would be just as forgeable-by-proxy."""
    headers = _client()._headers("an-admin@aiui.com")
    assert not [k for k in headers if k.lower() == "x-user-admin"], (
        "the webhook-handler is asserting admin-ness it cannot verify; the "
        "tasks service trusts X-User-Admin only because the API gateway is "
        "the only thing that sets it")


def test_no_cron_secret_leaks_into_the_user_path():
    """The other way to become exempt. The operator secret is for operators,
    and this client is holding a user's identity, not an operator's."""
    headers = _client()._headers("someone@example.com")
    assert not [k for k in headers if k.lower() == "x-cron-secret"]
    assert not [k for k in headers if k.lower() == "x-internal-secret"]
