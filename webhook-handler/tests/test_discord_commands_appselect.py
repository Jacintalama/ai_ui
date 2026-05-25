import asyncio
from handlers.discord_commands import DiscordCommandHandler, DEFERRED_CHANNEL_MESSAGE, DEFERRED_UPDATE_MESSAGE


class FakeDiscord:
    async def edit_original(self, **kwargs): pass
    async def post_channel_message(self, *a, **k): pass


class FakeRouter:
    def __init__(self):
        self.calls = []
    async def run_panel_menu(self, ctx, slug): self.calls.append(("menu", slug))
    async def run_panel_status(self, ctx, slug): self.calls.append(("status", slug))


def _component_payload(custom_id, *, component_type=2, values=None):
    data = {"custom_id": custom_id, "component_type": component_type}
    if values is not None:
        data["values"] = values
    return {"type": 3, "data": data, "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


async def test_select_returns_ephemeral_and_schedules_menu():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(
        _component_payload("aiuibuild:appselect", component_type=3, values=["shop"]))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
    await asyncio.sleep(0)
    assert ("menu", "shop") in router.calls


async def test_status_button_schedules_status():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(_component_payload("aiuibuild:status:shop"))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
    await asyncio.sleep(0)
    assert ("status", "shop") in router.calls


async def test_select_empty_values_is_noop():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(
        _component_payload("aiuibuild:appselect", component_type=3, values=[]))
    assert resp == {"type": DEFERRED_UPDATE_MESSAGE}
    await asyncio.sleep(0)
    assert router.calls == []


async def test_status_button_malformed_is_noop():
    # "aiuibuild:status:" has an empty slug -> slug_from_status_button raises -> no-op
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(_component_payload("aiuibuild:status:"))
    assert resp == {"type": DEFERRED_UPDATE_MESSAGE}
    await asyncio.sleep(0)
    assert router.calls == []
