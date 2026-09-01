"""What somebody has connected, and how to connect what they have not.

Read only by design. This is what lets the assistant say "you have no
ClickUp" instead of guessing, and every other thing it offers depends on
knowing that. Nothing here can change anything.
"""
from unittest.mock import AsyncMock

import pytest

import account_summary as acc


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
