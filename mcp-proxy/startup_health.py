"""Did the tools refresh actually work.

mcp-proxy retried its boot refresh only when the cache came back EMPTY. That is
almost never the failure that happens. When it and the tasks service were
rebuilt together, mcp-proxy won the race, every server it reaches over the
internal network refused the connection, and the 49 reachable ones answered
normally. 278 tools loaded, the retry condition read that as success, and the
34 per-user tools were simply absent until somebody restarted it by hand.

Nothing was unhealthy and nothing was logged as fatal, which is what made it
worth a named function instead of a tweak to an `if`.
"""
from typing import Dict, Iterable, Set


def servers_missing_tools(enabled_server_ids: Iterable[str],
                          tools_cache: Dict[str, dict]) -> Set[str]:
    """Enabled servers that contributed nothing to the cache.

    A server legitimately exposing zero tools is reported too. That costs a
    bounded retry and is the safe direction: the alternative is a server that
    silently never loads.
    """
    answered = {(info or {}).get("tenant_id")
                for info in (tools_cache or {}).values()}
    return {sid for sid in (enabled_server_ids or set()) if sid not in answered}
