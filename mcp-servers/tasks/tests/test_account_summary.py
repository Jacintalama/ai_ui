"""What somebody has connected, and how to connect what they have not.

Read only by design. This is what lets the assistant say "you have no
ClickUp" instead of guessing, and every other thing it offers depends on
knowing that. Nothing here can change anything.
"""
import pytest

import account_summary as acc
from connections import PROVIDERS as CANONICAL_PROVIDERS


@pytest.fixture
def nothing_connected(monkeypatch):
    async def fake(email):
        return set()
    monkeypatch.setattr(acc, "_connected_providers", fake)


@pytest.fixture
def some_connected(monkeypatch):
    async def fake(email):
        return {"gmail", "clickup"}
    monkeypatch.setattr(acc, "_connected_providers", fake)


async def test_it_says_what_is_connected_and_what_is_not(some_connected):
    out = await acc.summarise("owner@example.com")
    assert {c["id"] for c in out["connected"]} == {"gmail", "clickup"}
    not_connected_ids = {c["id"] for c in out["not_connected"]}
    assert "gmail" not in not_connected_ids
    assert "clickup" not in not_connected_ids


async def test_google_gets_a_login_link_and_clickup_gets_the_panel(nothing_connected):
    """Only a provider with a real, currently configured OAuth app can show
    a vendor login. Everything else takes a pasted key, so offering it a
    login tab would be a lie."""
    out = await acc.summarise("owner@example.com")
    by_id = {c["id"]: c for c in out["not_connected"]}
    assert by_id["gdrive"]["how"] == "login"
    assert by_id["clickup"]["how"] == "key"


async def test_every_unconnected_app_carries_a_link_the_model_can_print(nothing_connected):
    """The frontend turns this into a button. Without it the assistant can
    only tell somebody to go and find the Connections page themselves, which
    is the thing this feature exists to remove."""
    out = await acc.summarise("owner@example.com")
    for c in out["not_connected"]:
        assert c["connect_url"].startswith("#aiui-connect:")
        assert c["connect_url"].endswith(c["id"])


async def test_a_key_app_says_where_its_key_lives(nothing_connected):
    """Somebody who does not know how to connect ClickUp is not helped by
    being told to paste a key with no idea where to find one."""
    out = await acc.summarise("owner@example.com")
    clickup = next(c for c in out["not_connected"] if c["id"] == "clickup")
    assert clickup["where"], "no pointer to where the key comes from"


async def test_it_never_raises_when_the_connection_read_fails(monkeypatch):
    """A broken read must degrade to the emptiest honest answer, not stop
    the assistant answering at all."""
    async def boom(email):
        raise RuntimeError("down")
    monkeypatch.setattr(acc, "_connected_providers", boom)
    out = await acc.summarise("owner@example.com")
    assert out["connected"] == [] and out["not_connected"] == []


@pytest.mark.parametrize("email", ["", None])
async def test_nobody_gets_nothing(email):
    out = await acc.summarise(email)
    assert out["connected"] == [] and out["not_connected"] == []


def test_the_universe_is_exactly_eleven_real_apps():
    """The whole point of this fix: the assistant offers apps a person can
    actually connect, not whatever routes_agents.tools_for_email happens to
    list. Eleven is three Google services plus the eight Connect Your Own
    App providers, no more and no less."""
    assert len(acc.ALL_PROVIDER_IDS) == 11
    assert set(acc.ALL_PROVIDER_IDS) == (
        {"gmail", "calendar", "gdrive"} | set(CANONICAL_PROVIDERS)
    )


async def test_tools_never_appear_only_connectable_apps_do(nothing_connected):
    """server:mcp-proxy, documents, remember, excel_creator and
    executive_dashboard are Open WebUI tools, not connectable apps. Offering
    any of them here is the exact bug this fix removes."""
    out = await acc.summarise("owner@example.com")
    all_ids = {c["id"] for c in out["connected"]} | {c["id"] for c in out["not_connected"]}
    for forbidden in ("server:mcp-proxy", "documents", "remember",
                      "excel_creator", "executive_dashboard"):
        assert forbidden not in all_ids


async def test_every_entry_has_a_human_label_not_a_raw_id(nothing_connected):
    """A raw internal id like server:mcp-proxy in a chat button is exactly
    what this fix removes; every offer must carry a real label."""
    out = await acc.summarise("owner@example.com")
    for c in out["not_connected"]:
        assert c["label"], f"{c['id']} has no label"
        assert ":" not in c["label"], f"{c['id']} leaked a raw id as its label"


def test_a_provider_that_supports_oauth_but_is_not_configured_says_key(monkeypatch):
    """Notion supports OAuth in oauth_providers.py but has no client id and
    secret configured on this box today, so /oauth/start would 503. The
    assistant must not promise a login it cannot deliver."""
    import oauth_providers as O
    monkeypatch.setattr(O, "supports_oauth", lambda pid: pid == "notion")
    monkeypatch.setattr(O, "configured", lambda pid: False)
    hint = acc.connect_hint("notion")
    assert hint["how"] == "key"


def test_a_provider_that_supports_oauth_and_is_configured_says_login(monkeypatch):
    import oauth_providers as O
    monkeypatch.setattr(O, "supports_oauth", lambda pid: pid == "notion")
    monkeypatch.setattr(O, "configured", lambda pid: pid == "notion")
    hint = acc.connect_hint("notion")
    assert hint["how"] == "login"


def test_google_services_always_log_in_with_no_dependency_on_oauth_providers():
    for pid in acc.GOOGLE_SERVICES:
        assert acc._can_log_in(pid) is True


def test_no_dashes_in_any_hint():
    """Written with chr() rather than the characters or their escapes. The
    two earlier versions of this test in this repo both ended up containing
    the very characters they exist to forbid, because transcribing an escape
    is the step that renders it."""
    EM_DASH = chr(0x2014)
    EN_DASH = chr(0x2013)
    for pid in acc.ALL_PROVIDER_IDS:
        h = acc.connect_hint(pid)
        for value in h.values():
            if isinstance(value, str):
                assert EM_DASH not in value and EN_DASH not in value


def test_every_key_app_has_non_empty_label_and_where():
    """Labels and where strings must be present and non-empty for key apps,
    so the assistant can offer them to the user with full instructions."""
    for pid in acc.ALL_PROVIDER_IDS:
        h = acc.connect_hint(pid)
        if h["how"] == "key":
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
