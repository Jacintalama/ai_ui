"""Durable, cache-backed key/value store for conversational state.

Writes through to the tasks `bot_state` KV and keeps an in-memory cache, so a
read after a webhook-handler restart hydrates from Postgres. Best-effort: any
tasks-service error degrades to in-memory only and never breaks a chat turn.
"""
import logging
from typing import Any

logger = logging.getLogger("state_store")


class StateStore:
    def __init__(self, tasks_client):
        self._tasks = tasks_client
        self._cache: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        """Cache first; on a miss, hydrate from the tasks store (e.g. after a
        restart). Returns None if absent or the store is unreachable."""
        if key in self._cache:
            return self._cache[key]
        try:
            value = await self._tasks.get_state(key)
        except Exception:  # noqa: BLE001 - never break a chat turn
            return None
        if value is not None:
            self._cache[key] = value
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Write through: cache immediately, then persist (best-effort)."""
        self._cache[key] = value
        try:
            await self._tasks.set_state(key, value, ttl_seconds=ttl_seconds)
        except Exception:  # noqa: BLE001
            logger.debug("state persist skipped (in-memory only): %s", key)

    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        try:
            await self._tasks.delete_state(key)
        except Exception:  # noqa: BLE001
            pass
