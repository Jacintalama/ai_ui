"""'Open my schedules' must survive a user deleting their private thread.

Regression guard for the "#unknown channel" symptom: the dashboard thread id
is persisted on the DiscordLink. If the user deletes that thread, the stored
id is still truthy, so the old code reused it blindly — posting to a dead
thread (the post silently fails) and then pointing the ephemeral ACK at the
deleted thread, which Discord renders as ``#unknown``.

The handler must detect the failed post, recreate the thread, overwrite the
stale stored id, and only surface a thread link when a post actually landed.
"""
import asyncio

from handlers.discord_commands import (
    DiscordCommandHandler,
    DEFERRED_CHANNEL_MESSAGE,
)
from handlers.app_builder_panel import SCHED_OPEN_ID


class FakeDiscord:
    def __init__(self, dead_threads=(), next_thread_id="fresh-thread",
                 can_create=True):
        self.dead = set(dead_threads)
        self.next_thread_id = next_thread_id
        self.can_create = can_create
        self.created: list[tuple[str, str]] = []
        self.posts: list[tuple[str, str]] = []
        self.members: list[tuple[str, str]] = []
        self.edits: list[dict] = []

    async def edit_original(self, **kwargs):
        self.edits.append(kwargs)

    async def add_thread_member(self, thread_id, user_id):
        self.members.append((thread_id, user_id))
        return True

    async def create_private_thread(self, parent_channel_id, name):
        if not self.can_create:
            return None
        self.created.append((parent_channel_id, name))
        return self.next_thread_id

    async def post_channel_message(self, channel_id, content="",
                                   components=None, embeds=None):
        self.posts.append((channel_id, content))
        return channel_id not in self.dead


class FakeRouter:
    def __init__(self, stored_thread=None, dash=None):
        self._stored = stored_thread
        self._dash = dash if dash is not None else {
            "content": "DASH", "components": [{"x": 1}]}
        self.set_calls: list[tuple[str, str]] = []

    async def dashboard_payload(self, user_id):
        return self._dash

    async def get_user_thread(self, user_id):
        return self._stored

    async def set_user_thread(self, user_id, thread_id):
        self.set_calls.append((user_id, thread_id))
        return True


def _open_payload() -> dict:
    return {
        "type": 3,
        "data": {"custom_id": SCHED_OPEN_ID, "component_type": 2},
        "token": "tok",
        "channel_id": "c1",
        "member": {"user": {"id": "u1", "username": "ralph"}},
    }


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_deleted_thread_is_recreated_not_reused():
    """The reported bug: deleted thread → must recreate, not point at #unknown."""
    discord = FakeDiscord(dead_threads={"stale-123"}, next_thread_id="fresh-456")
    router = FakeRouter(stored_thread="stale-123")
    handler = DiscordCommandHandler(discord, router)

    resp = await handler.handle_interaction(_open_payload())
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    await _drain()

    # A fresh thread was created to replace the deleted one.
    assert discord.created, "should create a new thread when the stored one is gone"
    # The stale stored id was overwritten with the live thread.
    assert ("u1", "fresh-456") in router.set_calls
    # The ACK points at the LIVE thread, never the deleted one (#unknown).
    assert discord.edits, "must send a terminal follow-up"
    final = discord.edits[-1].get("content", "")
    assert "fresh-456" in final
    assert "stale-123" not in final


async def test_no_stored_thread_creates_one():
    discord = FakeDiscord(next_thread_id="new-1")
    router = FakeRouter(stored_thread=None)
    handler = DiscordCommandHandler(discord, router)

    await handler.handle_interaction(_open_payload())
    await _drain()

    assert discord.created, "no stored thread → must create one"
    assert ("u1", "new-1") in router.set_calls
    assert "new-1" in discord.edits[-1].get("content", "")


async def test_live_stored_thread_is_reused_not_recreated():
    discord = FakeDiscord()  # no dead threads → posts succeed
    router = FakeRouter(stored_thread="good-1")
    handler = DiscordCommandHandler(discord, router)

    await handler.handle_interaction(_open_payload())
    await _drain()

    assert not discord.created, "a live stored thread must be reused, not recreated"
    assert ("good-1", "u1") in discord.members
    assert "good-1" in discord.edits[-1].get("content", "")


async def test_cannot_open_thread_falls_back_to_ephemeral_dashboard():
    # Stored thread is dead AND a replacement can't be created.
    discord = FakeDiscord(dead_threads={"stale-9"}, can_create=False)
    router = FakeRouter(stored_thread="stale-9")
    handler = DiscordCommandHandler(discord, router)

    await handler.handle_interaction(_open_payload())
    await _drain()

    final = discord.edits[-1]
    # No thread link to a dead/#unknown channel — render the dashboard inline.
    assert "stale-9" not in final.get("content", "")
    assert final.get("content") == "DASH"
    assert final.get("components") == [{"x": 1}]
