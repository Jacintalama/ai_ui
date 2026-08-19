"""The tool index only ever grew.

store_tool_embeddings upserts and never deletes, so a tool that stops existing
stays searchable forever. On production that left 48 of the 346 indexed tools
pointing at servers that cannot run them:

  github-jacintalama  40 tools, registered and indexed, no container in either
                      compose file. It was a data-isolation demo.
  gmail                8 tools, disabled here because email goes through the
                      native Open WebUI tool instead.

Those tools were returned by search, described on request, and then failed at
execution. A one-off DELETE would have cleared them and let the next stale
server accumulate the same way, so the index prunes itself instead.

The rule: a row survives if its server is a currently registered, enabled
server. Not "a server that answered this boot" - a server that is up but
momentarily failed to list its tools must keep its rows, or one bad boot
empties the index.
"""
import pytest

from tool_embeddings import unknown_server_ids


LIVE = {"clickup", "github", "trello", "filesystem", "excel"}


def test_a_row_for_a_live_server_is_kept():
    assert unknown_server_ids({"clickup", "github"}, LIVE) == set()


def test_a_row_for_a_server_that_was_removed_from_the_registry_goes():
    """github-jacintalama, deleted from tenants.py in this change."""
    assert unknown_server_ids(
        {"clickup", "github-jacintalama"}, LIVE) == {"github-jacintalama"}


def test_a_row_for_a_disabled_server_goes():
    """gmail. `enabled` already gates what gets indexed; nothing gated what
    stayed indexed."""
    assert unknown_server_ids({"gmail", "excel"}, LIVE) == {"gmail"}


def test_an_empty_live_set_prunes_nothing():
    """The whole registry failing to load must not be read as "delete
    everything". Fail closed on destruction, not open."""
    assert unknown_server_ids({"clickup", "github"}, set()) == set()
    assert unknown_server_ids({"clickup"}, None) == set()


def test_an_empty_index_is_not_an_error():
    assert unknown_server_ids(set(), LIVE) == set()


def test_a_row_with_no_server_id_is_pruned():
    """Written by an older indexer that did not set tenant_id. It can never be
    matched to a server, so it can never be executed."""
    assert unknown_server_ids({"", "clickup"}, LIVE) == {""}
