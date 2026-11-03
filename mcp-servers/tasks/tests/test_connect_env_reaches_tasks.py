"""Every credential the connect code reads has to be handed to the container.

This is the bug that cost a day on 2026-10-30, written down as a test.
TRELLO_API_KEY was sitting in the server's .env, correct and complete, and
the one-click button was never offered to anybody. Nothing declared it on
the tasks service, so the container could not see it, `configured()` read
empty, and the only symptom was a feature that silently did not appear.

Nothing points at that from either end. The .env looks right, the code
looks right, and the gap is in a third file neither of them mentions.

So the list is DERIVED from the code rather than typed out here: adding a
provider to oauth_providers.PROVIDERS and forgetting compose fails this
test, rather than shipping a button nobody can press.
"""
import re

import pytest

import oauth_providers as O
import trello_connect as T
from repo_checkout import repo_root_or_skip

ROOT = repo_root_or_skip()
COMPOSE = ROOT / "docker-compose.unified.yml"


def _tasks_env():
    """The environment block of the tasks service, and only that one.

    Every service in this file has an environment block, so a bare search
    passes when the variable is declared on some other container, which is
    the same mistake in a different place.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    start = text.index("\n  tasks:\n")
    rest = text[start + 1:]
    end = re.search(r"\n  [a-z0-9][a-z0-9-]*:\n", rest)
    return rest[:end.start()] if end else rest


def _declared(name):
    return re.search(r"^\s*-\s*" + re.escape(name) + r"=", _tasks_env(),
                     re.M) is not None


def test_every_oauth_provider_has_its_credentials_passed_through():
    """An id with no secret cannot complete an exchange, so both or the
    button is a dead end."""
    missing = []
    for pid in sorted(O.PROVIDERS):
        for suffix in ("_CLIENT_ID", "_CLIENT_SECRET"):
            name = pid.upper() + suffix
            if not _declared(name):
                missing.append(name)
    assert missing == [], (
        "the tasks container cannot see these, so the Connect button will "
        "not appear however right the .env is: " + ", ".join(missing))


def test_the_trello_connect_key_is_passed_through():
    """The one that actually happened."""
    assert _declared(T.ENV_KEY)


def test_the_github_scope_is_passed_through():
    """Empty is a meaningful value for it, so it has to arrive as empty
    rather than not arrive at all."""
    assert _declared("GITHUB_SCOPE")


def test_the_github_app_slug_is_passed_through():
    """Without it the connect sends people to authorise rather than install,
    which grants no repository access and produces a connection that names
    the right person and reaches nothing."""
    assert _declared("GITHUB_APP_SLUG")


def test_the_scope_keeps_its_default_when_nobody_sets_it():
    """`-` and not `:-`. With `:-`, an empty value and an absent one are
    indistinguishable, and every deployment still on an OAuth App would
    silently stop asking for the scope it needs."""
    line = re.search(r"^\s*-\s*GITHUB_SCOPE=(.+)$", _tasks_env(), re.M)
    assert line, "GITHUB_SCOPE is not declared at all"
    value = line.group(1).strip()
    assert value == "${GITHUB_SCOPE-repo read:user}", value
    assert ":-" not in value, (
        "with :- an empty scope set on purpose is read as unset")


def test_a_provider_that_needs_nothing_is_not_demanded():
    """Trello is one-click without being OAuth 2.0, so it has no client id
    or secret and must not be required to have one."""
    assert "trello" not in O.PROVIDERS
