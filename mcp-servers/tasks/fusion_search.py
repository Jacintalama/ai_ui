"""Live web grounding for a Fusion turn.

Lives on its own rather than inside a route module because both the Fusion page
and the Open WebUI Fusion tool ground the same way, and the page may yet be
retired: the grounding must not be deleted along with it.

The platform already runs a Brave-backed search service, so this borrows it
rather than taking a second provider and a second key.
"""
import logging
import os

import httpx

log = logging.getLogger(__name__)

WEB_SEARCH_URL = os.environ.get(
    "WEB_SEARCH_URL", "http://mcp-web-search:8000/web_search")
RESULT_COUNT = 5
TIMEOUT_SECONDS = 12.0


async def web_search(query: str) -> list[dict]:
    """Live results for a query, or [] if search is unavailable.

    Never raises: search is an enhancement to a turn the user is already paying
    for, so a search outage degrades the answer instead of losing it.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            r = await client.post(WEB_SEARCH_URL,
                                  json={"query": query, "count": RESULT_COUNT})
            r.raise_for_status()
            return (r.json() or {}).get("results", []) or []
    except Exception:
        log.exception("fusion: web search failed for %r", query[:80])
        return []


def search_block(query: str, results: list[dict]) -> str:
    """Search results as text the models can read."""
    lines = [f'Web search results for "{query}", retrieved just now:', ""]
    for i, r in enumerate(results, 1):
        lines.append(f'{i}. {r.get("title", "")}')
        lines.append(f'   {r.get("url", "")}')
        snippet = " ".join((r.get("snippet") or "").split())
        if snippet:
            lines.append(f'   {snippet}')
        lines.append("")
    lines.append("These results are current. Prefer them over your training "
                 "data for anything time-sensitive, and cite the URLs you use. "
                 "If they do not cover the question, say so rather than "
                 "guessing.")
    return "\n".join(lines)


async def ground_in_search(messages: list[dict]) -> list[dict]:
    """Append live search results to the latest user turn.

    Every panel model gets the same block, so they answer from one shared set of
    facts instead of each model's own stale training data.
    """
    if not messages or messages[-1].get("role") != "user":
        return messages
    query = (messages[-1].get("content") or "").strip()
    if not query:
        return messages
    results = await web_search(query)
    if not results:
        return messages
    grounded = list(messages)
    grounded[-1] = {
        "role": "user",
        "content": f'{query}\n\n---\n{search_block(query, results)}',
    }
    return grounded
