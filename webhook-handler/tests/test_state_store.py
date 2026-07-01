"""StateStore: cache-first reads, write-through persistence, hydrate-on-miss,
graceful degradation, plus an end-to-end 'survives a restart' router check."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from clients.tasks import TasksAPIError
from handlers.state_store import StateStore
from handlers.commands import CommandRouter


def _store(tasks=None):
    return StateStore(tasks or MagicMock())


async def test_set_writes_through_then_serves_from_cache():
    tc = MagicMock()
    tc.set_state = AsyncMock()
    tc.get_state = AsyncMock(return_value=None)
    s = _store(tc)
    await s.set("k", {"a": 1}, ttl_seconds=60)
    tc.set_state.assert_awaited_once_with("k", {"a": 1}, ttl_seconds=60)
    assert await s.get("k") == {"a": 1}   # cache hit
    tc.get_state.assert_not_awaited()


async def test_get_hydrates_on_miss_then_caches():
    tc = MagicMock()
    tc.get_state = AsyncMock(return_value={"x": 2})
    s = _store(tc)
    assert await s.get("k") == {"x": 2}
    tc.get_state = AsyncMock(return_value=None)  # store now empty
    assert await s.get("k") == {"x": 2}          # still served from cache


async def test_get_absent_returns_none():
    tc = MagicMock()
    tc.get_state = AsyncMock(return_value=None)
    assert await _store(tc).get("nope") is None


async def test_degrades_when_store_unreachable():
    tc = MagicMock()
    tc.set_state = AsyncMock(side_effect=TasksAPIError(0, "down"))
    tc.get_state = AsyncMock(side_effect=TasksAPIError(0, "down"))
    s = _store(tc)
    await s.set("k", "v")               # persist fails, cache holds
    assert await s.get("k") == "v"      # from cache
    assert await s.get("other") is None  # store down -> None (no raise)


async def test_delete_clears_cache_and_store():
    tc = MagicMock()
    tc.set_state = AsyncMock()
    tc.delete_state = AsyncMock()
    tc.get_state = AsyncMock(return_value=None)
    s = _store(tc)
    await s.set("k", 1)
    await s.delete("k")
    tc.delete_state.assert_awaited_once_with("k")
    assert await s.get("k") is None


def _fake_tasks(shared: dict):
    """A tasks client whose state methods read/write a shared dict, so two router
    instances backed by it simulate a restart (fresh process, same Postgres)."""
    tc = MagicMock()

    async def get_state(k):
        return shared.get(k)

    async def set_state(k, v, ttl_seconds=None):
        shared[k] = v
        return True

    async def delete_state(k):
        shared.pop(k, None)
        return True

    tc.get_state = get_state
    tc.set_state = set_state
    tc.delete_state = delete_state
    return tc


async def test_pending_intent_survives_restart():
    shared: dict = {}
    r1 = CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                       discord_user_email_map={}, tasks_client=_fake_tasks(shared))
    tok = r1.park_intent("build_app", "a shop")
    for _ in range(5):          # let the fire-and-forget persist flush
        await asyncio.sleep(0)
    assert f"pending_intent:{tok}" in shared

    # "restart": a brand-new router with an empty cache, same backing store.
    r2 = CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                       discord_user_email_map={}, tasks_client=_fake_tasks(shared))
    assert tok not in r2._pending_intents          # cache is cold
    got = await r2.peek_intent(tok)                # hydrates from the store
    assert got is not None and got["intent"] == "build_app"


async def test_current_app_survives_restart():
    shared: dict = {}
    tc1 = _fake_tasks(shared)
    tc1.list_templates = AsyncMock(return_value=[])
    tc1.start_build = AsyncMock(return_value={"slug": "shop-9", "task_id": "t1"})
    r1 = CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                       discord_user_email_map={"100": "a@x.com"}, tasks_client=tc1)
    from handlers.commands import CommandContext
    ctx = CommandContext(user_id="100", user_name="t", channel_id="c", raw_text="",
                         subcommand="x", arguments="", platform="discord",
                         respond=AsyncMock(), metadata={})
    await r1._start_build(ctx, "a@x.com", None, "a coffee shop site")
    for _ in range(5):
        await asyncio.sleep(0)
    assert shared.get("current_app:100") == "shop-9"

    r2 = CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                       discord_user_email_map={}, tasks_client=_fake_tasks(shared))
    assert await r2._state.get("current_app:100") == "shop-9"
