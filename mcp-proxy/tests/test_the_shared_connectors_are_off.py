"""Nobody acts as somebody else any more: trello, github and n8n are off.

The finish of the boundary work. Until now, picking a `trello_*` tool made
the call as `clarenzbacalla`, a `github_*` tool as `Jacintalama`, and an
`n8n_*` tool as one anonymous API key, whoever had typed. Not because the
access code was wrong, which it is not, but because the per-user side could
not do the work, so the shared server was the only way.

#178, #179 and #180 fixed that half. Measured on the box after they
deployed:

    my-trello    7 -> 13 tools
    my-github   13 -> 21 tools

What is left on the shared side is niche: Trello's active-board session
state, which does not fit a per-user model at all, plus label CRUD, card
history, releases, tags, forks and `ui_get`.

WHY THIS IS SAFE, measured rather than argued:

  - No shared `trello`, `github` or `n8n` tool has EVER been called. All
    60 rows of `tasks.approval`, the whole history, hold my-clickup,
    my-trello, google-drive and one `clickup_*` call made before #139
    switched that one off.
  - Only the four ADMINS could reach them at all. `resolve_user_servers`
    strips SHARED out of grants, so the other five never had them.
  - #139 already did exactly this to `clickup`, which HAD been used, and
    nothing broke.

N8N IS NOT A SPECIAL CASE, though I argued it was for a day. I claimed
"there is one n8n instance, not nine n8n accounts, so the shared model may
be correct for it". The connect form disproves that: it asks for `base_url`
("Your n8n URL") as well as `api_key`, so it was built from the start for
somebody to point at their own instance. And nobody uses either side: 0 of
9 have connected an n8n, 0 automations and 0 schedules use it, and the
shared tools have never been called. So it is the CHEAPEST of the three to
switch off, not the hardest, which is the opposite of what the tool counts
suggested.

Switching the connector off does not touch the team's n8n instance or any
workflow on it. It stops agents reaching it with one anonymous key. Anybody
who wants that later connects it as their own, with that URL and their own
key, which is the rule for connected apps applied properly.
"""
import importlib
import io

import pytest

import tenants

#: The three, and the credential whose presence used to auto-enable each.
SHARED = {
    "trello": "TRELLO_API_KEY",
    "github": "GITHUB_TOKEN",
    "n8n": "N8N_API_KEY",
}


@pytest.fixture(autouse=True)
def _as_the_server_sees_it(monkeypatch):
    """Every assertion runs with all three credentials SET.

    Without this the file lies, exactly as the ClickUp one warned: these
    were `enabled=bool(os.getenv(...))`, so on a laptop with no credentials
    they are already False and a test would pass while the server, which
    HAS them, had them True. The credentials stay set because the
    containers themselves read them.
    """
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_whatever")
    for env in SHARED.values():
        monkeypatch.setenv(env, "set_for_this_test")
    # EVERY credential that could enable a SHARED server, read out of the
    # source rather than listed by hand.
    #
    # Setting only the three I was changing is what let this file lie on
    # 2026-11-11: `sonarqube` is enabled by bool(os.getenv("SONARQUBE_
    # TOKEN")), which is unset on a laptop, so it read disabled here and
    # "no shared connector is left enabled" passed while the server, which
    # HAS the token, had it on. That is the exact trap the ClickUp file's
    # fixture warns about, and I walked into it anyway.
    import re
    src = io.open(tenants.__file__, encoding="utf-8").read()
    entry = re.compile(r"MCPServerConfig\((.*?)\n    \),", re.S)
    takes_env = re.compile(r'enabled\s*=\s*bool\(os\.getenv\("([A-Z0-9_]+)"')
    for m in entry.finditer(src):
        block = m.group(1)
        if "AccessClass.SHARED" not in block:
            continue
        for env in takes_env.findall(block):
            monkeypatch.setenv(env, "set_for_this_test")
    importlib.reload(tenants)
    yield
    monkeypatch.undo()
    importlib.reload(tenants)


@pytest.mark.parametrize("sid", sorted(SHARED))
def test_the_shared_connector_is_not_enabled(sid):
    assert tenants.ALL_SERVERS[sid].enabled is False, (
        "the shared %s connector is reachable again; it acts as one "
        "person's account for everybody" % sid)


@pytest.mark.parametrize("sid,env", sorted(SHARED.items()))
def test_the_credential_is_no_longer_what_decides(sid, env):
    """The fixture has the credential set. If `enabled` still reads it,
    this change did not happen."""
    import inspect
    import re
    src = inspect.getsource(tenants)

    # The whole entry, to its closing paren at the dict's indent.
    #
    # NOT `block[:block.index("),")]`, which is what the ClickUp file does
    # and what I copied. That cuts at the FIRST "),", which for these three
    # is inside `endpoint_url=os.getenv("MCP_TRELLO_URL", "http://...")`,
    # so the `enabled=` line is never in the block and the assertion passes
    # on an entry it never read. It passed for trello while trello was
    # still auto-enabled, which is exactly the regression this test is for.
    m = re.search(r'\n    "%s": MCPServerConfig\((.*?)\n    \),'
                  % re.escape(sid), src, re.S)
    assert m, "could not find the %s entry" % sid
    block = m.group(1)
    assert "enabled" in block, (
        "the %s block does not contain its enabled= line, so this "
        "assertion would pass without reading anything" % sid)
    assert 'os.getenv("%s")' % env not in block, (
        "%s is auto-enabled by the presence of %s again" % (sid, env))


@pytest.mark.parametrize("sid", sorted(SHARED))
def test_the_per_user_replacement_is_still_on(sid):
    """Switching the shared one off must not leave people unable to reach
    the app at all."""
    mine = tenants.ALL_SERVERS["my-" + sid]
    assert mine.enabled is True
    assert mine.access_class == tenants.AccessClass.PUBLIC


def test_every_connectable_app_still_has_a_per_user_route():
    """The whole point. For each app somebody can connect, a PUBLIC
    per-user server must exist and be on."""
    for sid in sorted(SHARED):
        mine = tenants.ALL_SERVERS.get("my-" + sid)
        assert mine is not None and mine.enabled, sid


#: SHARED servers that are still on, each with the reason, so the test
#: below states the exception rather than hiding it.
#:
#: `sonarqube` is genuinely different from the four that were switched
#: off: there is no connect form for it (connections.py has no entry), so
#: there is no `my-sonarqube` and no per-user route to replace it with.
#: Switching it off would remove the capability outright rather than move
#: it onto each person's own account. Whether a shared SonarQube token is
#: acceptable is a decision, and it has its own card.
STILL_ON_ON_PURPOSE = {"sonarqube"}


def test_only_the_documented_exceptions_are_left_enabled():
    """A guard on the whole class, not on three names.

    This asserted `still_on == []` when it was written, and passed, and was
    WRONG on the server: the fixture set only the three credentials I was
    changing, so `sonarqube` read disabled on a laptop. Now the fixture
    sets every credential that enables a SHARED server, so this sees what
    production sees, and a new shared server has to be named here with a
    reason before it can pass.
    """
    still_on = {sid for sid, cfg in tenants.ALL_SERVERS.items()
                if cfg.access_class == tenants.AccessClass.SHARED
                and cfg.enabled}
    unexplained = sorted(still_on - STILL_ON_ON_PURPOSE)
    assert unexplained == [], (
        "these shared connectors are on and spend somebody else's "
        "credential, with no reason recorded: %s" % ", ".join(unexplained))


def test_the_four_we_switched_off_are_not_quietly_back():
    off = {sid for sid, cfg in tenants.ALL_SERVERS.items()
           if cfg.access_class == tenants.AccessClass.SHARED
           and not cfg.enabled}
    assert {"clickup", "trello", "github", "n8n"} <= off


def test_the_exception_list_is_not_a_place_to_hide_things():
    """Anything named in STILL_ON_ON_PURPOSE must actually exist and
    actually be SHARED, so a stale name cannot silently excuse a real
    server somebody adds with that id later."""
    for sid in STILL_ON_ON_PURPOSE:
        cfg = tenants.ALL_SERVERS.get(sid)
        assert cfg is not None, sid
        assert cfg.access_class == tenants.AccessClass.SHARED, sid


def test_the_per_user_servers_are_untouched_by_this():
    """Nothing here may switch off a my-* server."""
    off = sorted(sid for sid, cfg in tenants.ALL_SERVERS.items()
                 if sid.startswith("my-") and not cfg.enabled)
    assert off == [], off
