"""What a signed-in user may reach, and why "nothing configured" meant nothing.

The proxy indexed 346 tools and almost nobody could reach one. Measured on
production: two accounts saw everything (they were in the MCP-Admin group),
two saw 56 and 40, and the remaining five saw 4, 0, 0, 0 and 0. Two of the
five were platform admins. Being an admin of the platform granted no MCP
access at all, because only the MCP-Admin *group* was ever consulted.

Four separate faults produced that, and they share one root: access was
resolved by unioning grant sources and returning whatever came back, with
nothing asserted about the result.

  - the MCP-Admin path returned `list(ALL_SERVERS.keys())`, all 50 registered
    servers, though only 13 have a container. `enabled` was honoured in six
    other places and not in that one.
  - a user with no group and no row resolved to [], and there was no notion of
    a server that is safe to hand everyone, so [] was the honest answer.
  - group_tenant_mapping named five servers that were never deployed and
    omitted the three largest that were.

The rule these tests pin down: the answer is always intersected with what is
actually running, a server carrying no vendor credential is reachable without
a grant, and one that spends a shared credential is not.
"""
import pytest

from tenants import (
    ALL_SERVERS,
    AccessClass,
    MCPServerConfig,
    ServerTier,
    resolve_user_servers,
)


def _srv(server_id, access_class, enabled=True):
    return MCPServerConfig(
        server_id=server_id,
        display_name=server_id,
        tier=ServerTier.LOCAL,
        endpoint_url="http://example.invalid",
        auth_type="none",
        enabled=enabled,
        access_class=access_class,
    )


REGISTRY = {
    "excel": _srv("excel", AccessClass.PUBLIC),
    "web-search": _srv("web-search", AccessClass.PUBLIC),
    "scheduler": _srv("scheduler", AccessClass.RESTRICTED),
    "clickup": _srv("clickup", AccessClass.SHARED),
    "ghost-public": _srv("ghost-public", AccessClass.PUBLIC, enabled=False),
    "ghost-shared": _srv("ghost-shared", AccessClass.SHARED, enabled=False),
}


# --- a user with no grants is no longer a user with no tools --------------

def test_no_grants_still_reaches_the_servers_that_cost_nobody_anything():
    assert resolve_user_servers([], is_admin=False, servers=REGISTRY) == {
        "excel", "web-search"}


@pytest.mark.parametrize("nothing", [None, [], set(), ()])
def test_every_spelling_of_no_grants_behaves_the_same(nothing):
    assert resolve_user_servers(nothing, is_admin=False, servers=REGISTRY) == {
        "excel", "web-search"}


# --- but "everyone" stops at the shared credential ------------------------

def test_a_shared_credential_server_is_not_handed_out_by_default():
    """The rule chosen for the connections work: connect your own, or no
    access. Nobody ever acts as the platform's ClickUp account by default."""
    assert "clickup" not in resolve_user_servers(
        [], is_admin=False, servers=REGISTRY)


def test_a_restricted_server_is_not_handed_out_by_default():
    """scheduler carries no vendor credential, which is why it looks safe. It
    is not: mcp-servers/scheduler/main.py lists jobs via webhook-handler's
    /scheduler/user-jobs, which takes no user and returns everyone's, and
    scheduler_delete_cron_job can then delete any of them."""
    assert "scheduler" not in resolve_user_servers(
        [], is_admin=False, servers=REGISTRY)


def test_a_grant_is_what_unlocks_them():
    got = resolve_user_servers(["clickup", "scheduler"], is_admin=False,
                               servers=REGISTRY)
    assert {"clickup", "scheduler"} <= got


# --- the intersection that was missing on exactly one path ----------------

def test_a_disabled_server_never_appears_for_a_normal_user():
    got = resolve_user_servers(["ghost-shared"], is_admin=False,
                               servers=REGISTRY)
    assert "ghost-shared" not in got
    assert "ghost-public" not in got


def test_a_disabled_server_never_appears_for_an_admin_either():
    """The original bug, in one line: the admin path returned every registered
    key, so admins held grants to 37 servers with no container."""
    got = resolve_user_servers([], is_admin=True, servers=REGISTRY)
    assert "ghost-public" not in got
    assert "ghost-shared" not in got


def test_an_admin_reaches_everything_that_is_running():
    assert resolve_user_servers([], is_admin=True, servers=REGISTRY) == {
        "excel", "web-search", "scheduler", "clickup"}


def test_a_grant_for_a_server_that_does_not_exist_is_ignored():
    """group_tenant_mapping still names linear, atlassian, slack, gitlab and
    hubspot. None of them were ever deployed."""
    got = resolve_user_servers(["linear", "gitlab", "excel"], is_admin=False,
                               servers=REGISTRY)
    assert got == {"excel", "web-search"}


def test_the_result_is_always_a_set_never_none():
    for is_admin in (True, False):
        assert isinstance(
            resolve_user_servers(None, is_admin=is_admin, servers=REGISTRY),
            set)


# --- the real registry, not a fixture -------------------------------------

def test_every_registered_server_declares_an_access_class():
    """A server added without a class must not silently default to reachable
    by everyone. Explicit is the point of the field."""
    for server_id, cfg in ALL_SERVERS.items():
        assert isinstance(cfg.access_class, AccessClass), server_id


def test_the_vendor_credential_servers_are_not_public():
    """These five spend one shared vendor token. api_key_env cannot tell you
    that: it is MCP_API_KEY on every server, because that is the proxy's own
    key for reaching the container, not the vendor's."""
    for server_id in ("clickup", "github", "trello", "n8n", "sonarqube"):
        assert ALL_SERVERS[server_id].access_class is AccessClass.SHARED, server_id


def test_scheduler_is_restricted_not_public():
    assert ALL_SERVERS["scheduler"].access_class is AccessClass.RESTRICTED


def test_the_phantom_server_is_gone():
    """github-jacintalama was registered and had 40 tools indexed against it,
    and has no container in either compose file."""
    assert "github-jacintalama" not in ALL_SERVERS


def test_a_normal_user_reaches_the_expected_live_servers():
    """Guards the classification itself, against the real registry."""
    assert resolve_user_servers([], is_admin=False) == {
        "google-drive", "calendar", "filesystem", "web-search", "excel",
        "dashboard", "meeting-kb",
        # Per-user servers: each acts as the CALLER's own third-party account.
        "my-clickup", "my-github", "my-trello", "my-notion", "my-n8n"}


def test_the_per_user_servers_are_public_and_the_shared_ones_are_not():
    """The pair that makes the whole design safe. my-clickup is PUBLIC because
    it spends the caller's own credential and nothing that belongs to anyone
    else. clickup is SHARED because it spends one token belonging to one real
    person, so every task it creates is created by him."""
    for pid in ("clickup", "github", "trello", "notion", "n8n"):
        if pid in ALL_SERVERS:
            assert ALL_SERVERS[pid].access_class is not AccessClass.PUBLIC, pid
        assert ALL_SERVERS["my-" + pid].access_class is AccessClass.PUBLIC, pid


def test_a_per_user_server_points_at_our_own_service_not_a_vendor():
    """These carry decrypted credentials, so the endpoint must be the tasks
    service on the internal network, never something reachable from outside."""
    for pid in ("clickup", "github", "trello", "notion", "n8n"):
        url = ALL_SERVERS["my-" + pid].endpoint_url
        assert url.startswith("http://tasks:") or url.startswith("http://localhost"), url


# --- the wiring, not just the expression ----------------------------------
# resolve_user_servers being right proves nothing if get_user_tenants_async
# never calls it. That function is the one every endpoint actually reaches, and
# it cannot be imported into a check: a NameError inside a function body only
# shows up when the body runs. So it runs here, against a fake db module.

import sys
import types

import tenants as tenants_mod


class _FakeDB:
    def __init__(self, groups=(), group_tenants=(), user_tenants=(),
                 owui_admin=False):
        self._groups = list(groups)
        self._group_tenants = list(group_tenants)
        self._user_tenants = list(user_tenants)
        self._owui_admin = owui_admin

    async def get_user_groups(self, email):
        return self._groups

    async def get_tenants_from_groups(self, groups):
        return self._group_tenants

    async def get_user_tenants(self, email):
        return self._user_tenants

    async def is_openwebui_admin(self, email):
        return self._owui_admin


@pytest.fixture
def fake_db(monkeypatch):
    def install(**kwargs):
        mod = types.ModuleType("db")
        fake = _FakeDB(**kwargs)
        for name in ("get_user_groups", "get_tenants_from_groups",
                     "get_user_tenants", "is_openwebui_admin"):
            setattr(mod, name, getattr(fake, name))
        monkeypatch.setitem(sys.modules, "db", mod)
        return mod
    return install


LIVE_PUBLIC = {"google-drive", "calendar", "filesystem", "web-search",
               "excel", "dashboard", "meeting-kb",
               "my-clickup", "my-github", "my-trello", "my-notion", "my-n8n"}


async def test_a_user_with_nothing_configured_now_gets_the_public_set(fake_db):
    """Four of the nine production users were in exactly this state, and four
    of them resolved to zero tools."""
    fake_db()
    got = await tenants_mod.get_user_tenants_async("nobody@example.com")
    assert set(got) == LIVE_PUBLIC


async def test_an_openwebui_admin_is_an_mcp_admin(fake_db):
    """The reason ralphbenitez32 saw 4 tools and clidebacalla saw 0 while both
    were platform admins: only the MCP-Admin group was ever consulted."""
    fake_db(owui_admin=True)
    got = await tenants_mod.get_user_tenants_async("boss@example.com")
    assert set(got) == {sid for sid, c in tenants_mod.ALL_SERVERS.items()
                        if c.enabled}
    assert set(got) > LIVE_PUBLIC


async def test_the_admin_path_no_longer_returns_dead_servers(fake_db):
    """It returned list(ALL_SERVERS.keys()): 50 registered, 13 with a
    container."""
    fake_db(groups=["MCP-Admin"])
    got = await tenants_mod.get_user_tenants_async("admin@example.com")
    assert all(tenants_mod.ALL_SERVERS[sid].enabled for sid in got)
    assert len(got) < len(tenants_mod.ALL_SERVERS)


async def test_stale_grants_for_undeployed_servers_are_dropped(fake_db):
    """What group_tenant_mapping actually contains today."""
    fake_db(groups=["Everyone"],
            group_tenants=["linear", "atlassian", "slack", "gitlab", "hubspot"])
    got = await tenants_mod.get_user_tenants_async("user@example.com")
    assert set(got) == LIVE_PUBLIC


async def test_a_real_grant_still_widens_access(fake_db):
    fake_db(user_tenants=["scheduler"])
    got = await tenants_mod.get_user_tenants_async("user@example.com")
    assert "scheduler" in got


async def test_a_db_failure_does_not_widen_access(fake_db):
    """Fails closed: if the admin check raises, the caller is not an admin."""
    mod = fake_db()

    async def boom(email):
        raise RuntimeError("connection refused")

    mod.is_openwebui_admin = boom
    mod.get_user_tenants = boom
    got = await tenants_mod.get_user_tenants_async("user@example.com")
    assert set(got) == LIVE_PUBLIC


# --- the second copy of the rule ------------------------------------------
# Two functions answered "may this user reach this server". get_user_tenants_async
# decides what SEARCH returns; user_has_tenant_access_async decides what EXECUTION
# allows. Fixing only the first produced a state where a tool could be found,
# described, and then refused with 403 by the endpoint that runs it. That is the
# same shape as the auth hole before it and as the missing `enabled` filter: one
# rule, several implementations, wrong in some of them. So the second no longer
# reimplements anything, it asks the first.

async def test_execution_allows_exactly_what_search_offers(fake_db):
    fake_db()
    email = "nobody@example.com"
    offered = set(await tenants_mod.get_user_tenants_async(email))
    assert offered, "fixture should offer the public set"
    for server_id in offered:
        assert await tenants_mod.user_has_tenant_access_async(email, server_id), \
            server_id


async def test_execution_refuses_exactly_what_search_withholds(fake_db):
    fake_db()
    email = "nobody@example.com"
    offered = set(await tenants_mod.get_user_tenants_async(email))
    withheld = {sid for sid, c in tenants_mod.ALL_SERVERS.items()
                if c.enabled} - offered
    assert withheld, "fixture should withhold the shared servers"
    for server_id in withheld:
        assert not await tenants_mod.user_has_tenant_access_async(
            email, server_id), server_id


async def test_a_per_user_server_is_executable_without_any_grant(fake_db):
    """The regression that shipped: my-github was searchable and then 403'd on
    call, because only the search path knew about access classes."""
    fake_db()
    for pid in ("my-github", "my-clickup", "my-trello", "my-notion", "my-n8n"):
        assert await tenants_mod.user_has_tenant_access_async(
            "nobody@example.com", pid), pid


async def test_a_disabled_server_is_never_executable(fake_db):
    fake_db(user_tenants=["gmail"])
    assert not await tenants_mod.user_has_tenant_access_async(
        "nobody@example.com", "gmail")


async def test_an_admin_can_execute_everything_a_normal_user_cannot(fake_db):
    """Not written against a named server: the shared ones are enabled only
    when their vendor token is in the environment, so naming clickup here
    passes on the server and fails on a laptop for reasons unrelated to access.
    """
    fake_db(owui_admin=True)
    for server_id in (sid for sid, c in tenants_mod.ALL_SERVERS.items()
                      if c.enabled):
        assert await tenants_mod.user_has_tenant_access_async(
            "boss@example.com", server_id), server_id


async def test_only_an_admin_reaches_beyond_the_public_set(fake_db):
    fake_db(owui_admin=True)
    admin = set(await tenants_mod.get_user_tenants_async("boss@example.com"))
    fake_db(owui_admin=False)
    plain = set(await tenants_mod.get_user_tenants_async("user@example.com"))
    assert plain == LIVE_PUBLIC
    assert admin >= plain
