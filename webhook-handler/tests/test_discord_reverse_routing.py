import asyncio
from handlers.discord_commands import (
    DiscordCommandHandler, DEFERRED_CHANNEL_MESSAGE, MODAL)


class FakeDiscord:
    async def edit_original(self, **kwargs): pass
    async def post_channel_message(self, *a, **k): pass


class FakeRouter:
    def __init__(self):
        self.reverse_calls = []
    async def run_panel_reverse(self, ctx, role, location, jobdesc, count):
        self.reverse_calls.append((role, location, jobdesc, count))


def _component(custom_id):
    return {"type": 3, "data": {"custom_id": custom_id, "component_type": 2},
            "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


def _modal(custom_id, values):
    comps = [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
             for k, v in values.items()]
    return {"type": 5, "data": {"custom_id": custom_id, "components": comps},
            "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


async def test_rev_find_button_returns_reverse_modal():
    h = DiscordCommandHandler(FakeDiscord(), FakeRouter())
    resp = await h.handle_interaction(_component("aiuiout:revfind"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "aiuiout:revmodal"
    assert resp["data"]["title"] == "Find Jobs"


async def test_rev_modal_submit_spawns_run_panel_reverse():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(_modal("aiuiout:revmodal", {
        "role": "Backend", "location": "Berlin", "jobdesc": "6 yrs Python",
        "count": "8"}))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE}
    await asyncio.sleep(0)  # let the spawned task run
    assert router.reverse_calls == [("Backend", "Berlin", "6 yrs Python", 8)]
