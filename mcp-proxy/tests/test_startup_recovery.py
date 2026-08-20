"""What counts as a successful tools refresh.

mcp-proxy refreshes its tool cache at boot and retries "if it failed". Failure
was defined as an EMPTY cache, which is almost never what happens. When
mcp-proxy and tasks were rebuilt together, mcp-proxy came up first, every one
of the eight per-user servers it reaches over the internal network refused the
connection, and the other 49 servers answered fine. 278 tools loaded, the
condition read that as success, and 34 tools stayed missing until somebody
noticed and restarted it by hand.

Nothing was logged as an error at the end, nothing was unhealthy, and the tools
were simply absent. So "did anything load" is replaced by "did everything that
should have loaded, load".
"""
from startup_health import servers_missing_tools


ENABLED = {"clickup", "github", "my-clickup", "my-github", "meeting-kb"}


def _cache(*server_ids):
    return {f"{sid}_tool{i}": {"tenant_id": sid}
            for i, sid in enumerate(server_ids)}


def test_a_server_that_answered_is_not_missing():
    assert servers_missing_tools(ENABLED, _cache(*ENABLED)) == set()


def test_the_servers_that_answered_nothing_are_named():
    """The real incident: everything on the internal network refused while the
    rest answered."""
    cache = _cache("clickup", "github", "meeting-kb")
    assert servers_missing_tools(ENABLED, cache) == {"my-clickup", "my-github"}


def test_a_partly_loaded_cache_is_not_treated_as_success():
    """The whole bug in one assertion: a non-empty cache said 'done'."""
    cache = _cache("clickup")
    assert cache, "this case needs a NON-empty cache"
    assert servers_missing_tools(ENABLED, cache)


def test_an_empty_cache_reports_everything_missing():
    assert servers_missing_tools(ENABLED, {}) == ENABLED


def test_a_cached_tool_for_an_unknown_server_does_not_mask_a_gap():
    """A stale entry left over from a server that has since been removed must
    not count as that server answering."""
    cache = _cache("clickup", "github", "meeting-kb")
    cache["ghost_tool"] = {"tenant_id": "long-gone"}
    assert "my-clickup" in servers_missing_tools(ENABLED, cache)


def test_nothing_enabled_means_nothing_missing():
    assert servers_missing_tools(set(), _cache("clickup")) == set()
