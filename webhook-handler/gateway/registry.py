"""Which platforms exist, and which of them are actually usable right now.

hermes-agent's registry carries a plugin system, a setup_fn and a platform_hint.
All three are real ideas and none earns its keep at two platforms, so they are
left out until a third one asks for them.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Callable

from gateway.base import BasePlatformAdapter

log = logging.getLogger(__name__)


@dataclass
class PlatformEntry:
    name: str
    label: str
    adapter_factory: Callable[[], BasePlatformAdapter]
    required_env: list[str] = field(default_factory=list)
    max_message_length: int = 0          # telegram: 4096.  0 means no cap.
    emoji: str = "🔌"


class PlatformRegistry:
    """Dormant by default: a platform whose required_env is unset never wakes up.

    So this whole feature can ship to production before any bot token exists,
    and deploying it changes nothing visible.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PlatformEntry] = {}
        self._adapters: dict[str, BasePlatformAdapter] = {}

    def register(self, entry: PlatformEntry) -> None:
        self._entries[entry.name] = entry
        # Drop any cached adapter so a re-register cannot hand out a stale one.
        self._adapters.pop(entry.name, None)

    def all_names(self) -> list[str]:
        return list(self._entries)

    def is_enabled(self, name: str) -> bool:
        entry = self._entries.get(name)
        if entry is None:
            return False
        return all(os.environ.get(var, "").strip() for var in entry.required_env)

    def enabled(self) -> list[PlatformEntry]:
        return [e for n, e in self._entries.items() if self.is_enabled(n)]

    def adapter(self, name: str) -> BasePlatformAdapter | None:
        """One long-lived adapter per platform, built on first use.

        Cached deliberately: a fresh client per inbound message would open a new
        connection pool every time on a box with 3.8GB of RAM.
        """
        if not self.is_enabled(name):
            return None
        if name not in self._adapters:
            entry = self._entries[name]
            adapter = entry.adapter_factory()
            adapter.name = entry.name
            adapter.max_message_length = entry.max_message_length
            self._adapters[name] = adapter
            log.info("gateway: %s adapter ready", name)
        return self._adapters[name]


#: The process-wide registry. main.py registers into this at import time.
registry = PlatformRegistry()
