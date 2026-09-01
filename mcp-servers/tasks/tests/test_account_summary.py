"""What somebody has connected, and how to connect what they have not.

Read only by design. This is what lets the assistant say "you have no
ClickUp" instead of guessing, and every other thing it offers depends on
knowing that. Nothing here can change anything.
"""
from unittest.mock import AsyncMock

import pytest

import account_summary as acc
from connections import PROVIDERS as CANONICAL_PROVIDERS


@pytest.fixture
def tools(monkeypatch):
    async def fake(email):
        return {"tools": [
            {"id": "gmail", "label": "Gmail", "connected": True},
            {"id": "gdrive", "label": "Google Drive", "connected": False},
            {"id": "clickup", "label": "ClickUp", "connected": False},
        ]}
    monkeypatch.setattr(acc, "tools_for_email", fake)


async def test_it_says_what_is_connected_and_what_is_not(tools):
    out = await acc.summarise("owner@example.com")
    assert [c["id"] for c in out["connected"]] == ["gmail"]
    assert {c["id"] for c in out["not_connected"]} == {"gdrive", "clickup"}


async def test_google_gets_a_login_link_and_clickup_gets_the_panel(tools):
    """Only Google and Notion have a registered OAuth app. Everything else
    takes a pasted key, so offering it a login tab would be a lie."""
    out = await acc.summarise("owner@example.com")
    by_id = {c["id"]: c for c in out["not_connected"]}
    assert by_id["gdrive"]["how"] == "login"
    assert by_id["clickup"]["how"] == "key"


async def test_every_unconnected_app_carries_a_link_the_model_can_print(tools):
    """The frontend turns this into a button. Without it the assistant can
    only tell somebody to go and find the Connections page themselves, which
    is the thing this feature exists to remove."""
    out = await acc.summarise("owner@example.com")
    for c in out["not_connected"]:
        assert c["connect_url"].startswith("#aiui-connect:")
        assert c["connect_url"].endswith(c["id"])


async def test_a_key_app_says_where_its_key_lives(tools):
    """Somebody who does not know how to connect ClickUp is not helped by
    being told to paste a key with no idea where to find one."""
    out = await acc.summarise("owner@example.com")
    clickup = next(c for c in out["not_connected"] if c["id"] == "clickup")
    assert clickup["where"], "no pointer to where the key comes from"


async def test_it_never_raises_when_the_tools_read_fails(monkeypatch):
    """A broken read must degrade to the emptiest honest answer, not stop
    the assistant answering at all."""
    async def boom(email):
        raise RuntimeError("down")
    monkeypatch.setattr(acc, "tools_for_email", boom)
    out = await acc.summarise("owner@example.com")
    assert out["connected"] == [] and out["not_connected"] == []


async def test_it_never_raises_when_tools_is_not_iterable(monkeypatch):
    """If the vendor returns {"tools": 42} instead of a list, the module must
    gracefully degrade rather than crash with TypeError."""
    async def fake(email):
        return {"tools": 42}
    monkeypatch.setattr(acc, "tools_for_email", fake)
    out = await acc.summarise("owner@example.com")
    assert out["connected"] == [] and out["not_connected"] == []


async def test_it_skips_entries_with_non_string_id(monkeypatch):
    """If a tool entry has an integer id instead of a string, it must be
    skipped silently, not crash when concatenating with #aiui-connect:."""
    async def fake(email):
        return {"tools": [
            {"id": "gmail", "label": "Gmail", "connected": True},
            {"id": 123, "label": "BadTool", "connected": False},
            {"id": "clickup", "label": "ClickUp", "connected": False},
        ]}
    monkeypatch.setattr(acc, "tools_for_email", fake)
    out = await acc.summarise("owner@example.com")
    assert [c["id"] for c in out["connected"]] == ["gmail"]
    assert {c["id"] for c in out["not_connected"]} == {"clickup"}


@pytest.mark.parametrize("email", ["", None])
async def test_nobody_gets_nothing(email):
    out = await acc.summarise(email)
    assert out["connected"] == [] and out["not_connected"] == []


def test_only_google_and_notion_can_show_a_login():
    """If this set grows, somebody registered a real OAuth app with that
    vendor. It is not a code change on its own."""
    assert acc.OAUTH_PROVIDERS == frozenset({"gmail", "gdrive", "calendar", "notion"})


def test_no_dashes_in_any_hint():
    """Written with chr() rather than the characters or their escapes. The
    two earlier versions of this test in this repo both ended up containing
    the very characters they exist to forbid, because transcribing an escape
    is the step that renders it."""
    EM_DASH = chr(0x2014)
    EN_DASH = chr(0x2013)
    for pid in acc.PROVIDERS:
        h = acc.connect_hint(pid)
        for value in h.values():
            if isinstance(value, str):
                assert EM_DASH not in value and EN_DASH not in value


def test_every_key_app_has_non_empty_label_and_where():
    """Labels and where strings must be present and non-empty for key apps,
    so the assistant can offer them to the user with full instructions."""
    for pid in acc.PROVIDERS:
        if pid not in acc.OAUTH_PROVIDERS:
            h = acc.connect_hint(pid)
            assert h["label"], f"{pid} has empty label"
            assert h["where"], f"{pid} has empty where"


def test_where_strings_come_from_canonical_source():
    """The where strings must come from connections.py to prevent drift
    between the connection UI and the assistant's guidance."""
    for pid in ["clickup", "zapier"]:
        h = acc.connect_hint(pid)
        canonical = CANONICAL_PROVIDERS.get(pid)
        if canonical:
            assert h["where"] == canonical.where, \
                f"{pid} where mismatch: got {h['where']!r}, expected {canonical.where!r}"
