"""The ingest secret must reach the container, not just the code.

On 2026-08-03 the meetings service was locked down: every endpoint had been
unauthenticated, and `curl https://ai-ui.coolestdomain.win/meetings/` returned
all 21 records with full transcripts. POST/PUT kept working for the n8n ingest
workflow via a shared secret, `MEETINGS_INGEST_SECRET`.

That variable was added to `main.py` and to the tests — and to nothing else.
It was absent from `.env`, absent from `docker-compose.unified.yml`, and unset
in the running container. `_is_ingester` deliberately fails closed on an empty
secret, so ingest returned 403 rather than working. Verified live on
2026-08-12 with an empty body that could never insert:

    POST /meetings/  no auth                 -> 403
    POST /meetings/  n8n's exact bearer JWT  -> 403
    records afterwards: 21, unchanged

The auth tests could not catch this: they `monkeypatch.setenv` the value
themselves, so they prove the CODE honours a secret while saying nothing about
whether the deployed process has one. This file closes that specific gap by
asserting on the compose file the server actually runs.

It is a config assertion, not a behaviour test, and it is written that way on
purpose — the failure was config, and CLAUDE.md's standing lesson is that a
guarantee nothing checks is not a guarantee.
"""
import pathlib
import re

import pytest

COMPOSE = pathlib.Path(__file__).resolve().parents[3] / "docker-compose.unified.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.exists(), reason="compose file not present in this checkout")

TEXT = COMPOSE.read_text(encoding="utf-8")


def _meetings_block() -> str:
    """The mcp-meetings service block, up to the next top-level service."""
    start = TEXT.index("  mcp-meetings:")
    rest = TEXT[start + 1:]
    m = re.search(r"\n  [a-z0-9_-]+:\n", rest)
    return rest[: m.start()] if m else rest


def test_the_compose_file_still_defines_mcp_meetings():
    """Guards the assertions below against a rename silently emptying them."""
    assert "  mcp-meetings:" in TEXT


def test_the_ingest_secret_is_passed_to_the_container():
    """The whole bug: the code read a variable the container never received."""
    assert "MEETINGS_INGEST_SECRET" in _meetings_block(), (
        "mcp-meetings does not receive MEETINGS_INGEST_SECRET, so "
        "_is_ingester fails closed and every n8n ingest POST returns 403")


def test_the_secret_is_not_given_a_default():
    """An unset secret must keep the ingest path CLOSED. A default like
    `${MEETINGS_INGEST_SECRET:-changeme}` would hand every anonymous caller a
    working credential — worse than the outage it fixes."""
    block = _meetings_block()
    line = next(l for l in block.splitlines() if "MEETINGS_INGEST_SECRET" in l
                and not l.strip().startswith("#"))
    assert ":-" not in line, (
        f"the ingest secret has a default value ({line.strip()}); an unset "
        f"secret must close the path, never open it with a known value")
